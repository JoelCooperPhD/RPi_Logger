
import asyncio
import datetime
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from Modules.base.io_utils import get_versioned_filename
from Modules.base.recording import RecordingManagerBase
from ..camera_utils import FrameTimingMetadata
from ..constants import DEFAULT_BITRATE_BPS, FPS_MIN, FPS_MAX, FFMPEG_TIMEOUT_SECONDS
from .csv_logger import CSVLogger
from .encoder import H264EncoderWrapper
from .overlay import FrameOverlayHandler

logger = logging.getLogger(__name__)


class CameraRecordingManager(RecordingManagerBase):

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
        super().__init__(device_id=f"camera_{camera_id}")
        self.camera_id = camera_id
        self.picam2 = picam2
        self.resolution = resolution
        self.fps = fps
        self.bitrate = bitrate
        self.enable_csv_logging = enable_csv_logging
        self.auto_remux = auto_remux
        self.video_path: Optional[Path] = None
        self.frame_timing_path: Optional[Path] = None

        self._encoder = H264EncoderWrapper(picam2, bitrate)
        self._csv_logger: Optional[CSVLogger] = None
        self._overlay = FrameOverlayHandler(camera_id, overlay_config or {}, enable_overlay)

        self._latest_lock = threading.Lock()
        self._written_frames = 0
        self._recording_start_time: Optional[float] = None

        self._csv_stop_task: Optional[asyncio.Task] = None

        self.picam2.post_callback = self._overlay.create_callback()
        logger.info("Camera %d: Registered overlay callback", camera_id)

    @property
    def written_frames(self) -> int:
        return self._written_frames

    @property
    def recorded_frame_count(self) -> int:
        return self._overlay.get_frame_count()

    async def start_recording(self, session_dir: Path, trial_number: int = 1) -> Path:
        if self._is_recording:
            if self.video_path:
                return self.video_path
            raise RuntimeError("Already recording but no video path set")

        # Set session context
        self._current_session_dir = session_dir
        self._current_trial_number = trial_number

        await asyncio.to_thread(session_dir.mkdir, parents=True, exist_ok=True)

        session_name = session_dir.name
        if "_" in session_name:
            session_timestamp = session_name.split("_", 1)[1]
        else:
            session_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        w, h = self.resolution
        base_name = f"CAM{self.camera_id}_{w}x{h}_{self.fps:.1f}fps_{session_timestamp}"

        self.video_path = session_dir / f"{base_name}_trial{trial_number:03d}.h264"

        timing_filename = get_versioned_filename(session_dir, datetime.datetime.now())
        self.frame_timing_path = session_dir / timing_filename

        self._written_frames = 0
        self._recording_start_time = time.perf_counter()
        self._overlay.reset_frame_count()
        self._overlay.set_recording(True)

        if self.enable_csv_logging:
            self._csv_logger = CSVLogger(self.camera_id, self.frame_timing_path, trial_number)
            try:
                self._csv_logger.start()
            except RuntimeError as e:
                logger.warning("Failed to start CSV logger: %s, disabling CSV logging", e)
                self._csv_logger = None

        # Start hardware-accelerated recording (offload to thread pool to avoid blocking)
        try:
            await asyncio.to_thread(self._encoder.start, self.video_path)
        except Exception as e:
            logger.error("Failed to start H264 encoder for camera %d: %s", self.camera_id, e)
            if self._csv_logger is not None:
                self._csv_logger.stop()
                self._csv_logger = None
            self._recording_start_time = None
            raise

        self._is_recording = True
        csv_status = "with CSV logging" if self.enable_csv_logging else "CSV logging disabled"
        logger.info("Camera %d recording to %s (%s) [hardware H.264 @ %d bps]",
                   self.camera_id, self.video_path, csv_status, self.bitrate)

        return self.video_path

    async def stop_recording(self) -> dict:
        if not self._is_recording and not self._encoder.is_running:
            return {
                'duration_seconds': 0.0,
                'frames_written': 0,
                'frames_dropped': 0,
                'output_files': [],
            }

        # Calculate stats before clearing
        duration = 0.0
        if self._recording_start_time is not None:
            duration = time.perf_counter() - self._recording_start_time
        frames_written = self._written_frames
        output_files = []

        self._is_recording = False
        self._overlay.set_recording(False)

        # Stop hardware encoder (offload to thread pool to avoid blocking 100-500ms)
        await asyncio.to_thread(self._encoder.stop)

        # NOTE: Keep _csv_logger reference until stop task completes to prevent
        if self._csv_logger is not None:
            try:
                loop = asyncio.get_running_loop()
                self._csv_stop_task = asyncio.create_task(self._csv_logger.stop())
            except RuntimeError:
                self._csv_logger = None

        # Collect output files
        if self.video_path:
            output_files.append(self.video_path)
        if self.frame_timing_path and self.frame_timing_path.exists():
            output_files.append(self.frame_timing_path)

        # Run asynchronously to avoid blocking
        if self.auto_remux and self.video_path and self.video_path.exists():
            mp4_path = self.video_path.with_suffix('.mp4')

            # Validate inputs before calling ffmpeg
            if not (FPS_MIN <= self.fps <= FPS_MAX):
                logger.warning("Invalid FPS %.2f for ffmpeg (must be %0.1f-%0.1f), skipping remux",
                             self.fps, FPS_MIN, FPS_MAX)
                return {
                    'duration_seconds': duration,
                    'frames_written': frames_written,
                    'frames_dropped': 0,  # Cameras don't track dropped frames currently
                    'output_files': output_files,
                }

            # Resolve paths to absolute to prevent confusion
            h264_path = self.video_path.resolve()
            mp4_path_resolved = mp4_path.resolve()

            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(self._async_remux(h264_path, mp4_path_resolved, mp4_path))
            except RuntimeError:
                logger.warning("No event loop available for ffmpeg remux, keeping .h264 file")
                if self.video_path:
                    logger.info("Camera %d recording saved (H.264): %s", self.camera_id, self.video_path)
        elif self.video_path:
            logger.info("Camera %d recording saved (H.264): %s", self.camera_id, self.video_path)

        # Reset recording start time
        self._recording_start_time = None

        return {
            'duration_seconds': duration,
            'frames_written': frames_written,
            'frames_dropped': 0,  # Cameras don't track dropped frames currently
            'output_files': output_files,
        }

    async def pause_recording(self):
        raise NotImplementedError("Pause not supported by camera recording")

    async def resume_recording(self):
        raise NotImplementedError("Resume not supported by camera recording")

    async def cleanup(self) -> None:
        await self.stop_recording()

        if self._csv_stop_task is not None:
            try:
                await asyncio.wait_for(self._csv_stop_task, timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("CSV logger stop task timed out after 2 seconds")
            except Exception as e:
                logger.warning("Error waiting for CSV logger stop: %s", e)
            finally:
                self._csv_stop_task = None
                self._csv_logger = None

    def get_stats(self) -> dict:
        """Get current recording statistics"""
        duration = 0.0
        if self._is_recording and self._recording_start_time is not None:
            duration = time.perf_counter() - self._recording_start_time

        return {
            'is_recording': self._is_recording,
            'duration_seconds': duration,
            'frames_written': self._written_frames,
            'recorded_frame_count': self._overlay.get_frame_count(),
            'video_path': str(self.video_path) if self.video_path else None,
            'frame_timing_path': str(self.frame_timing_path) if self.frame_timing_path else None,
        }

    async def _async_remux(self, h264_path: Path, mp4_path_resolved: Path, mp4_path: Path) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y',
                '-r', str(self.fps),
                '-i', str(h264_path),
                '-c:v', 'copy',
                str(mp4_path_resolved),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await asyncio.wait_for(process.wait(), timeout=FFMPEG_TIMEOUT_SECONDS)

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

    def write_frame(self, frame: Optional[np.ndarray], metadata: FrameTimingMetadata) -> None:
        """
        Write a frame with metadata (for CSV logging).

        Note: The actual video encoding is handled by the hardware encoder
        via the picam2 callback chain, not through this method.
        This method is primarily for CSV metadata logging.
        """
        if not self._is_recording or not self.enable_csv_logging:
            return

        with self._latest_lock:
            self._written_frames += 1
            frame_number = metadata.display_frame_index if metadata.display_frame_index is not None else self._written_frames

        if self._csv_logger is not None:
            self._csv_logger.log_frame(frame_number, metadata)
