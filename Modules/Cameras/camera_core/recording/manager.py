#!/usr/bin/env python3
"""
Camera recording manager - coordinates hardware encoding, CSV logging, and overlays.

Main public interface for camera recording operations.
Uses picamera2 H264Encoder for hardware-accelerated encoding.
"""

import asyncio
import datetime
import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from ..camera_utils import FrameTimingMetadata
from ..constants import DEFAULT_BITRATE_BPS, FPS_MIN, FPS_MAX, FFMPEG_TIMEOUT_SECONDS
from .csv_logger import CSVLogger
from .encoder import H264EncoderWrapper
from .overlay import FrameOverlayHandler

logger = logging.getLogger("CameraRecorder")


class CameraRecordingManager:
    """
    Camera recorder with hardware H.264 encoding via picamera2.

    Coordinates:
    - Hardware H.264 encoding (zero-copy, minimal CPU)
    - CSV timing logs (separate thread)
    - Frame overlays (zero-copy via post_callback)
    - MP4 remuxing (optional, post-recording)

    Args:
        camera_id: Camera identifier
        picam2: Picamera2 instance (required for encoder attachment)
        resolution: Recording resolution (width, height)
        fps: Target frames per second
        bitrate: Video bitrate in bits per second
        enable_csv_logging: Enable CSV timing logs
        auto_remux: Automatically convert H.264 to MP4 after recording
        enable_overlay: Enable frame number overlay
        overlay_config: Overlay configuration dictionary
    """

    def __init__(
        self,
        camera_id: int,
        picam2,
        resolution: tuple[int, int],
        fps: float,
        bitrate: int = DEFAULT_BITRATE_BPS,
        enable_csv_logging: bool = True,
        auto_remux: bool = True,
        enable_overlay: bool = True,
        overlay_config: dict = None
    ):
        self.camera_id = camera_id
        self.picam2 = picam2
        self.resolution = resolution
        self.fps = fps
        self.bitrate = bitrate
        self.enable_csv_logging = enable_csv_logging
        self.auto_remux = auto_remux

        self.recording = False
        self.video_path: Optional[Path] = None
        self.frame_timing_path: Optional[Path] = None

        # Components
        self._encoder = H264EncoderWrapper(picam2, bitrate)
        self._csv_logger: Optional[CSVLogger] = None
        self._overlay = FrameOverlayHandler(camera_id, overlay_config or {}, enable_overlay)

        # Frame tracking
        self._latest_lock = threading.Lock()
        self._written_frames = 0

        # Task tracking for proper cleanup
        self._csv_stop_task: Optional[asyncio.Task] = None

        # Register overlay callback immediately (works for both preview and recording)
        self.picam2.post_callback = self._overlay.create_callback()
        logger.info("Camera %d: Registered overlay callback", camera_id)

    @property
    def written_frames(self) -> int:
        """Number of frames written to recording"""
        return self._written_frames

    @property
    def is_recording(self) -> bool:
        """Check if currently recording"""
        return self.recording

    @property
    def recorded_frame_count(self) -> int:
        """Get total frame count from overlay (includes preview and recording frames)"""
        return self._overlay.get_frame_count()

    def start_recording(self, session_dir: Path) -> None:
        """
        Start recording to session directory.

        Args:
            session_dir: Directory to save recordings
        """
        if self.recording:
            return

        session_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        w, h = self.resolution
        base_name = f"cam{self.camera_id}_{w}x{h}_{self.fps:.1f}fps_{timestamp}"

        # Use .h264 extension for raw H.264 output
        self.video_path = session_dir / f"{base_name}.h264"
        self.frame_timing_path = session_dir / f"{base_name}_frame_timing.csv"

        # Reset state
        self._written_frames = 0
        self._overlay.reset_frame_count()
        self._overlay.set_recording(True)

        # Start CSV logger if enabled
        if self.enable_csv_logging:
            self._csv_logger = CSVLogger(self.camera_id, self.frame_timing_path)
            try:
                self._csv_logger.start()
            except RuntimeError as e:
                # No event loop - skip CSV logging
                logger.warning("Failed to start CSV logger: %s, disabling CSV logging", e)
                self._csv_logger = None

        # Start hardware-accelerated recording
        try:
            self._encoder.start(self.video_path)
        except Exception as e:
            logger.error("Failed to start H264 encoder for camera %d: %s", self.camera_id, e)
            # Cleanup CSV logger if encoder fails
            if self._csv_logger is not None:
                self._csv_logger.stop()
                self._csv_logger = None
            raise

        self.recording = True
        csv_status = "with CSV logging" if self.enable_csv_logging else "CSV logging disabled"
        logger.info("Camera %d recording to %s (%s) [hardware H.264 @ %d bps]",
                   self.camera_id, self.video_path, csv_status, self.bitrate)

    def stop_recording(self) -> None:
        """Stop recording and optionally remux to MP4"""
        if not self.recording and not self._encoder.is_running:
            return

        self.recording = False
        self._overlay.set_recording(False)

        # Stop hardware encoder (critical: do this immediately)
        self._encoder.stop()

        # Stop CSV logging (track task for proper cleanup)
        if self._csv_logger is not None:
            # Schedule async stop and track the task
            try:
                loop = asyncio.get_running_loop()
                self._csv_stop_task = asyncio.create_task(self._csv_logger.stop())
            except RuntimeError:
                # No event loop - logger will be cleaned up by GC
                pass
            self._csv_logger = None

        # Convert .h264 to .mp4 for better compatibility (if enabled)
        # Run asynchronously to avoid blocking
        if self.auto_remux and self.video_path and self.video_path.exists():
            mp4_path = self.video_path.with_suffix('.mp4')

            # Validate inputs before calling ffmpeg
            if not (FPS_MIN <= self.fps <= FPS_MAX):
                logger.warning("Invalid FPS %.2f for ffmpeg (must be %0.1f-%0.1f), skipping remux",
                             self.fps, FPS_MIN, FPS_MAX)
                return

            # Resolve paths to absolute to prevent confusion
            h264_path = self.video_path.resolve()
            mp4_path_resolved = mp4_path.resolve()

            # Try to schedule async remux, fall back gracefully if no event loop
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(self._async_remux(h264_path, mp4_path_resolved, mp4_path))
            except RuntimeError:
                # No event loop - log .h264 file and skip remux
                # This shouldn't happen in normal operation since camera runs in async context
                logger.warning("No event loop available for ffmpeg remux, keeping .h264 file")
                if self.video_path:
                    logger.info("Camera %d recording saved (H.264): %s", self.camera_id, self.video_path)
        elif self.video_path:
            logger.info("Camera %d recording saved (H.264): %s", self.camera_id, self.video_path)

    async def cleanup(self) -> None:
        """Clean up recording resources (async to await CSV logger stop)"""
        self.stop_recording()

        # Wait for CSV logger to finish closing (with timeout)
        if self._csv_stop_task is not None:
            try:
                await asyncio.wait_for(self._csv_stop_task, timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("CSV logger stop task timed out after 2 seconds")
            except Exception as e:
                logger.warning("Error waiting for CSV logger stop: %s", e)
            finally:
                self._csv_stop_task = None

    async def _async_remux(self, h264_path: Path, mp4_path_resolved: Path, mp4_path: Path) -> None:
        """
        Asynchronously convert .h264 to .mp4 using ffmpeg.

        Args:
            h264_path: Source .h264 file path
            mp4_path_resolved: Resolved destination .mp4 file path
            mp4_path: Destination .mp4 file path (for updating self.video_path)
        """
        try:
            # Run ffmpeg as async subprocess
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y',
                '-r', str(self.fps),
                '-i', str(h264_path),
                '-c:v', 'copy',
                str(mp4_path_resolved),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Wait for completion with timeout
            await asyncio.wait_for(process.wait(), timeout=FFMPEG_TIMEOUT_SECONDS)

            # Remove original .h264 file
            h264_path.unlink()
            self.video_path = mp4_path
            logger.info("Camera %d recording saved (MP4): %s", self.camera_id, self.video_path)

        except asyncio.TimeoutError:
            logger.warning("ffmpeg conversion timed out for camera %d. Keeping .h264 file.",
                         self.camera_id)
            if self.video_path:
                logger.info("Camera %d recording saved (H.264): %s", self.camera_id, self.video_path)
        except Exception as e:
            logger.warning("Failed to convert .h264 to .mp4 for camera %d: %s. Keeping .h264 file.",
                         self.camera_id, e)
            if self.video_path:
                logger.info("Camera %d recording saved (H.264): %s", self.camera_id, self.video_path)

    def submit_frame(self, frame: Optional[np.ndarray], metadata: FrameTimingMetadata) -> None:
        """
        Log frame timing metadata to CSV.

        Note: With hardware H.264 encoding + post_callback overlay:
        - Frame pixels go directly from camera → post_callback → encoder
        - This method only handles CSV logging for diagnostics
        - frame parameter can be None (not needed for CSV logging)

        Args:
            frame: Frame data (not used, can be None)
            metadata: Frame timing metadata
        """
        if not self.recording or not self.enable_csv_logging:
            return

        with self._latest_lock:
            self._written_frames += 1
            frame_number = metadata.display_frame_index if metadata.display_frame_index is not None else self._written_frames

        # Queue CSV logging (non-blocking)
        if self._csv_logger is not None:
            self._csv_logger.log_frame(frame_number, metadata)
