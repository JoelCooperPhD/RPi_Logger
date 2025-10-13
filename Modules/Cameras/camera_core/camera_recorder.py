#!/usr/bin/env python3
"""
Camera recording manager with consistent FPS and detailed timing diagnostics.
Uses picamera2 H264Encoder for hardware-accelerated encoding.

OPTIMIZED FOR PERFORMANCE:
- Hardware H.264 encoding via picamera2 (minimal CPU usage)
- Separate CSV logging thread to avoid blocking video writes
- Configurable CSV logging (can disable for performance)
- Increased flush intervals to reduce disk I/O stuttering
"""

import datetime
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Optional, NamedTuple

import cv2
import numpy as np
from picamera2 import MappedArray
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

from .camera_utils import FrameTimingMetadata

logger = logging.getLogger("CameraRecorder")


class _CSVLogEntry(NamedTuple):
    """Entry for CSV logging queue"""
    frame_number: int
    write_time_unix: float
    write_start_monotonic: float
    write_end_monotonic: float
    enqueued_monotonic: float
    metadata: FrameTimingMetadata
    backlog_after: int
    last_write_monotonic: Optional[float]
    last_camera_frame_index: Optional[int]


class CameraRecordingManager:
    """
    Camera recorder with hardware H.264 encoding via picamera2.

    Uses picamera2 H264Encoder for efficient hardware-accelerated recording.
    Drops frames when camera can't keep up (no duplication).
    Automatically remuxes video with correct FPS based on actual timing data.

    Args:
        picam2: Picamera2 instance (required for encoder attachment)
        auto_remux: If True (default), automatically correct video FPS after recording
    """

    def __init__(self, camera_id: int, picam2, resolution: tuple[int, int], fps: float, bitrate: int = 10_000_000,
                 enable_csv_logging: bool = True, auto_remux: bool = True, enable_overlay: bool = True, overlay_config: dict = None):
        self.camera_id = camera_id
        self.picam2 = picam2
        self.resolution = resolution
        self.fps = fps
        self.bitrate = bitrate
        self.enable_csv_logging = enable_csv_logging
        self.auto_remux = auto_remux
        self.enable_overlay = enable_overlay
        self.overlay_config = overlay_config or {}

        self.recording = False
        self.video_path: Optional[Path] = None
        self.frame_timing_path: Optional[Path] = None

        self._encoder: Optional[H264Encoder] = None
        self._output: Optional[FileOutput] = None
        self._frame_timing_file: Optional[Any] = None
        self._csv_queue: Optional[queue.Queue[_CSVLogEntry]] = None
        self._csv_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._queue_sentinel = object()

        self._latest_lock = threading.Lock()
        self._written_frames = 0
        self._skipped_frames = 0
        self._recorded_frame_count = 0  # Frames processed by post_callback

        # Drop tracking (accumulates drops even when recorder skips frames)
        self._accumulated_drops = 0  # Drops not yet written to CSV
        self._total_hardware_drops = 0  # Total drops since recording started

        # Store original callback to restore later
        self._original_callback = None

    @property
    def written_frames(self) -> int:
        return self._written_frames

    @property
    def skipped_frames(self) -> int:
        return self._skipped_frames

    @property
    def is_recording(self) -> bool:
        return self.recording

    def _overlay_callback(self, request):
        """
        Post-callback that adds overlay to BOTH main and lores streams.

        This is called by picamera2 for every frame before encoding/display.
        We add frame number overlay here so it appears identically on both:
        - main stream → H.264 encoder → recording
        - lores stream → capture loop → preview

        CRITICAL: Uses MappedArray to get DIRECT access to frame buffers.
        This ensures cv2.putText modifications affect what encoder/preview see.
        Using make_array() would return a COPY, which wouldn't affect encoding.

        EFFICIENCY: Overlay is rendered ONCE per stream at camera level,
        not duplicated in Python processing code. Single source of truth.
        """
        if not self.enable_overlay:
            return request

        try:
            # Increment recorded frame count
            self._recorded_frame_count += 1

            # Get overlay configuration
            font_scale = self.overlay_config.get('font_scale_base', 0.6)
            thickness = self.overlay_config.get('thickness_base', 1)

            # Text color (BGR in config → RGB for picamera2)
            text_color_b = self.overlay_config.get('text_color_b', 0)
            text_color_g = self.overlay_config.get('text_color_g', 0)
            text_color_r = self.overlay_config.get('text_color_r', 0)
            text_color = (text_color_r, text_color_g, text_color_b)

            margin_left = self.overlay_config.get('margin_left', 10)
            line_start_y = self.overlay_config.get('line_start_y', 30)

            frame_text = f"Frame: {self._recorded_frame_count}"

            # Add overlay to MAIN stream (for recording) when encoder is running
            if self.recording and self._encoder is not None:
                try:
                    with MappedArray(request, "main") as m:
                        cv2.putText(
                            m.array,
                            frame_text,
                            (margin_left, line_start_y),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            font_scale,
                            text_color,
                            thickness,
                            cv2.LINE_AA
                        )
                except Exception as e:
                    if self._recorded_frame_count <= 3:
                        logger.warning("Camera %d: Could not overlay on main stream: %s", self.camera_id, e)

        except Exception as e:
            logger.error("Error in overlay callback for camera %d: %s", self.camera_id, e)

        return request

    def start_recording(self, session_dir: Path) -> None:
        if self.recording:
            return

        session_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        w, h = self.resolution
        base_name = f"cam{self.camera_id}_{w}x{h}_{self.fps:.1f}fps_{timestamp}"

        # Use .h264 extension for raw H.264 output
        self.video_path = session_dir / f"{base_name}.h264"
        self.frame_timing_path = session_dir / f"{base_name}_frame_timing.csv"

        # Create H264 encoder with hardware acceleration
        self._encoder = H264Encoder(bitrate=self.bitrate)
        self._output = FileOutput(str(self.video_path))

        # Initialize CSV logging if enabled
        if self.enable_csv_logging:
            self._frame_timing_file = open(self.frame_timing_path, "w", encoding="utf-8", buffering=8192)
            self._frame_timing_file.write(
                "frame_number,write_time_unix,sensor_timestamp_ns,dropped_since_last,total_hardware_drops\n"
            )
            # CSV logging queue (larger to prevent blocking)
            self._csv_queue = queue.Queue(maxsize=300)

        self._stop_event.clear()
        self._written_frames = 0
        self._skipped_frames = 0
        self._recorded_frame_count = 0
        self._accumulated_drops = 0
        self._total_hardware_drops = 0

        # NOTE: post_callback is now registered permanently at camera init
        # No need to register/unregister during recording start/stop

        # Start hardware-accelerated recording
        try:
            self.picam2.start_encoder(self._encoder, self._output)
        except Exception as e:
            logger.error("Failed to start H264 encoder for camera %d: %s", self.camera_id, e)
            raise

        # Start CSV logger thread if enabled
        if self.enable_csv_logging:
            self._csv_thread = threading.Thread(target=self._csv_logger_loop, name=f"Cam{self.camera_id}-csv", daemon=True)
            self._csv_thread.start()

        self.recording = True
        csv_status = "with CSV logging" if self.enable_csv_logging else "CSV logging disabled"
        logger.info("Camera %d recording to %s (%s) [hardware H.264 @ %d bps]",
                   self.camera_id, self.video_path, csv_status, self.bitrate)

    def stop_recording(self) -> None:
        if not self.recording and self._encoder is None:
            return

        self.recording = False
        self._stop_event.set()

        # Stop hardware encoder (critical: do this immediately to unblock camera)
        if self._encoder is not None:
            try:
                logger.debug("Camera %d: Stopping H264 encoder...", self.camera_id)
                self.picam2.stop_encoder()
                logger.debug("Camera %d: Encoder stopped", self.camera_id)
            except Exception as e:
                logger.warning("Error stopping encoder for camera %d: %s", self.camera_id, e)
            self._encoder = None
            self._output = None

        # NOTE: post_callback stays registered (permanent overlay for preview+recording)
        # No need to restore/unregister

        # Stop CSV logging thread
        if self._csv_queue is not None:
            try:
                self._csv_queue.put_nowait(self._queue_sentinel)
            except queue.Full:
                pass

        if self._csv_thread is not None:
            self._csv_thread.join(timeout=5.0)
        self._csv_thread = None
        self._csv_queue = None

        # Close CSV file
        if self._frame_timing_file is not None:
            self._frame_timing_file.flush()
            self._frame_timing_file.close()
            self._frame_timing_file = None

        # Convert .h264 to .mp4 for better compatibility (if enabled)
        if self.auto_remux and self.video_path and self.video_path.exists():
            mp4_path = self.video_path.with_suffix('.mp4')
            try:
                import subprocess
                # Use ffmpeg to remux H.264 to MP4 container with correct FPS
                subprocess.run([
                    'ffmpeg', '-y',
                    '-r', str(self.fps),  # Input framerate
                    '-i', str(self.video_path),
                    '-c:v', 'copy',  # Copy video stream (no re-encoding)
                    str(mp4_path)
                ], check=True, capture_output=True)

                # Remove original .h264 file
                self.video_path.unlink()
                self.video_path = mp4_path
                logger.info("Camera %d recording saved (MP4): %s", self.camera_id, self.video_path)
            except Exception as e:
                logger.warning("Failed to convert .h264 to .mp4 for camera %d: %s. Keeping .h264 file.", self.camera_id, e)
                if self.video_path:
                    logger.info("Camera %d recording saved (H.264): %s", self.camera_id, self.video_path)
        elif self.video_path:
            logger.info("Camera %d recording saved (H.264): %s", self.camera_id, self.video_path)

    def cleanup(self) -> None:
        self.stop_recording()

    def submit_frame(self, frame: Optional[np.ndarray], metadata: FrameTimingMetadata) -> None:
        """
        Log frame timing metadata to CSV.

        Note: With hardware H.264 encoding + post_callback overlay:
        - Frame pixels go directly from camera → post_callback → encoder
        - This method only handles CSV logging for diagnostics
        - frame parameter can be None (not needed for CSV logging)
        """
        if not self.recording or not self.enable_csv_logging:
            return

        with self._latest_lock:
            # Track frame count
            self._written_frames += 1

            # Accumulate any drops from this frame
            if metadata.dropped_since_last is not None and metadata.dropped_since_last > 0:
                self._accumulated_drops += metadata.dropped_since_last
                self._total_hardware_drops += metadata.dropped_since_last

            # Queue CSV logging
            if self._csv_queue is not None:
                write_time_unix = time.time()
                frame_number = metadata.display_frame_index if metadata.display_frame_index is not None else self._written_frames

                csv_entry = _CSVLogEntry(
                    frame_number=frame_number,
                    write_time_unix=write_time_unix,
                    write_start_monotonic=time.perf_counter(),
                    write_end_monotonic=time.perf_counter(),
                    enqueued_monotonic=time.perf_counter(),
                    metadata=metadata,
                    backlog_after=0,
                    last_write_monotonic=None,
                    last_camera_frame_index=metadata.camera_frame_index,
                )
                try:
                    self._csv_queue.put_nowait(csv_entry)
                except queue.Full:
                    pass  # Drop CSV entry if queue full

    def _csv_logger_loop(self) -> None:
        """
        SEPARATE THREAD: Handle all CSV logging operations without blocking video writes.
        """
        csv_write_counter = 0
        csv_flush_interval = 60  # Flush CSV every N frames (~2 sec at 30fps)

        while not self._stop_event.is_set():
            if self._csv_queue is None:
                break
            try:
                entry = self._csv_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if entry is self._queue_sentinel:
                break

            # Process CSV entry
            self._log_frame_timing_impl(entry)

            # Batch flush
            csv_write_counter += 1
            if csv_write_counter >= csv_flush_interval:
                if self._frame_timing_file is not None:
                    self._frame_timing_file.flush()
                csv_write_counter = 0

        # Final flush
        if self._frame_timing_file is not None:
            self._frame_timing_file.flush()

        logger.debug("Camera %d CSV logger loop exited", self.camera_id)

    def _log_frame_timing_impl(self, entry: _CSVLogEntry) -> None:
        """
        Process and write CSV log entry (runs in separate thread)
        """
        if self._frame_timing_file is None:
            return

        # Use pre-calculated dropped frame count from hardware timestamp analysis
        # This is calculated in the capture loop using SensorTimestamp deltas
        # Note: We use the frame's own drop count if available, but if the recorder
        # skipped frames, we need to get the accumulated count
        dropped_since_last = entry.metadata.dropped_since_last

        # Get accumulated drops from recorder (includes drops from skipped frames)
        # IMPORTANT: Must use lock to avoid race with submit_frame()
        with self._latest_lock:
            accumulated_drops = self._accumulated_drops
            total_drops = self._total_hardware_drops

            # If we have accumulated drops, use that instead (handles skipped frames)
            if accumulated_drops > 0:
                dropped_since_last = accumulated_drops
                # Reset accumulated drops AFTER using them
                self._accumulated_drops = 0

        # Debug: Log first few frames and any drops
        if entry.frame_number <= 5 or (dropped_since_last is not None and dropped_since_last > 0):
            logger.info("Frame %d: hardware_frame_number=%s, software_frame_index=%s, dropped=%s, accumulated=%s, total=%s",
                       entry.frame_number,
                       entry.metadata.camera_frame_index,
                       entry.metadata.software_frame_index,
                       dropped_since_last,
                       accumulated_drops,
                       total_drops)

        # Format and write CSV row - minimal format with only essential data
        row = (
            f"{entry.frame_number},"
            f"{entry.write_time_unix:.6f},"
            f"{entry.metadata.sensor_timestamp_ns if entry.metadata.sensor_timestamp_ns is not None else ''},"
            f"{dropped_since_last if dropped_since_last is not None else ''},"
            f"{total_drops}\n"
        )

        self._frame_timing_file.write(row)
