#!/usr/bin/env python3
"""
Camera recording manager with consistent FPS and detailed timing diagnostics.
Handles video encoding via ffmpeg and frame timing CSV output.

OPTIMIZED FOR PERFORMANCE:
- Separate CSV logging thread to avoid blocking video writes
- Direct numpy-to-bytes write to ffmpeg (minimal overhead)
- Configurable CSV logging (can disable for performance)
- Increased flush intervals to reduce disk I/O stuttering
"""

import datetime
import logging
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional, NamedTuple

import cv2
import numpy as np

from .camera_utils import FrameTimingMetadata, _QueuedFrame
from .video_remux import auto_remux_recording

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
    Camera recorder with frame-drop mode and automatic FPS correction.

    Drops frames when camera can't keep up (no duplication).
    Automatically remuxes video with correct FPS based on actual timing data.

    Args:
        auto_remux: If True (default), automatically correct video FPS after recording
    """

    def __init__(self, camera_id: int, resolution: tuple[int, int], fps: float, enable_csv_logging: bool = True, auto_remux: bool = True):
        self.camera_id = camera_id
        self.resolution = resolution
        self.fps = fps
        self.enable_csv_logging = enable_csv_logging
        self.auto_remux = auto_remux

        self.recording = False
        self.video_path: Optional[Path] = None
        self.frame_timing_path: Optional[Path] = None

        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._frame_timing_file: Optional[Any] = None
        self._frame_queue: Optional[queue.Queue[_QueuedFrame]] = None
        self._csv_queue: Optional[queue.Queue[_CSVLogEntry]] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._csv_thread: Optional[threading.Thread] = None
        self._timer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._queue_sentinel = object()

        self._latest_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_metadata: Optional[FrameTimingMetadata] = None

        self._frame_interval = 1.0 / fps if fps > 0 else 0.0
        self._next_frame_time: Optional[float] = None
        self._written_frames = 0
        self._skipped_frames = 0
        self._last_write_monotonic: Optional[float] = None
        self._last_camera_frame_index: Optional[int] = None

        # Drop tracking (accumulates drops even when recorder skips frames)
        self._accumulated_drops = 0  # Drops not yet written to CSV
        self._total_hardware_drops = 0  # Total drops since recording started

        # Batch flushing for performance
        # Increased intervals to reduce disk I/O stuttering
        self._video_write_counter = 0
        self._video_flush_interval = 120  # Flush video every N frames (~4 sec at 30fps)

    @property
    def written_frames(self) -> int:
        return self._written_frames

    @property
    def skipped_frames(self) -> int:
        return self._skipped_frames

    @property
    def is_recording(self) -> bool:
        return self.recording

    def start_recording(self, session_dir: Path) -> None:
        if self.recording:
            return

        session_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        w, h = self.resolution
        base_name = f"cam{self.camera_id}_{w}x{h}_{self.fps:.1f}fps_{timestamp}"

        self.video_path = session_dir / f"{base_name}.mp4"
        self.frame_timing_path = session_dir / f"{base_name}_frame_timing.csv"

        pix_fmt = "bgr24"
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            f"{w}x{h}",
            "-pix_fmt",
            pix_fmt,
            "-r",
            str(self.fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            str(self.video_path),
        ]

        try:
            self._ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg is required for recording but was not found") from exc

        # Initialize CSV logging if enabled
        if self.enable_csv_logging:
            self._frame_timing_file = open(self.frame_timing_path, "w", encoding="utf-8", buffering=8192)
            self._frame_timing_file.write(
                "frame_number,write_time_unix,sensor_timestamp_ns,dropped_since_last,total_hardware_drops\n"
            )
            # CSV logging queue (larger to prevent blocking)
            self._csv_queue = queue.Queue(maxsize=300)

        max_queue = max(int(self.fps * 4), 60)
        self._frame_queue = queue.Queue(max_queue)
        self._stop_event.clear()
        self._next_frame_time = time.perf_counter()
        self._written_frames = 0
        self._skipped_frames = 0
        self._last_write_monotonic = None
        self._last_camera_frame_index = None
        self._accumulated_drops = 0
        self._total_hardware_drops = 0

        # Start threads: video writer (high priority), CSV logger (low priority), timer
        self._writer_thread = threading.Thread(target=self._frame_writer_loop, name=f"Cam{self.camera_id}-writer", daemon=True)
        self._writer_thread.start()

        if self.enable_csv_logging:
            self._csv_thread = threading.Thread(target=self._csv_logger_loop, name=f"Cam{self.camera_id}-csv", daemon=True)
            self._csv_thread.start()

        self._timer_thread = threading.Thread(target=self._frame_timer_loop, name=f"Cam{self.camera_id}-timer", daemon=True)
        self._timer_thread.start()

        self.recording = True
        csv_status = "with CSV logging" if self.enable_csv_logging else "CSV logging disabled"
        logger.info("Camera %d recording to %s (%s)", self.camera_id, self.video_path, csv_status)

    def stop_recording(self) -> None:
        if not self.recording and self._ffmpeg_process is None:
            return

        self.recording = False
        self._stop_event.set()

        if self._frame_queue is not None:
            try:
                self._frame_queue.put_nowait(self._queue_sentinel)
            except queue.Full:
                pass

        if self._csv_queue is not None:
            try:
                self._csv_queue.put_nowait(self._queue_sentinel)
            except queue.Full:
                pass

        if self._timer_thread is not None:
            self._timer_thread.join(timeout=2.0)
        self._timer_thread = None

        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5.0)
        self._writer_thread = None

        if self._csv_thread is not None:
            self._csv_thread.join(timeout=5.0)
        self._csv_thread = None

        if self._frame_queue is not None:
            while not self._frame_queue.empty():
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    break
        self._frame_queue = None
        self._csv_queue = None

        if self._ffmpeg_process is not None:
            try:
                # Flush any remaining buffered video data
                if self._ffmpeg_process.stdin is not None:
                    self._ffmpeg_process.stdin.flush()
                self._ffmpeg_process.stdin.close()
                self._ffmpeg_process.wait(timeout=5)
            except Exception:
                self._ffmpeg_process.terminate()
            self._ffmpeg_process = None

        if self._frame_timing_file is not None:
            # Flush any remaining buffered CSV data
            self._frame_timing_file.flush()
            self._frame_timing_file.close()
            self._frame_timing_file = None

        self._latest_frame = None
        self._latest_metadata = None

        # Auto-remux video with correct FPS if enabled
        if self.video_path and self.auto_remux and self.enable_csv_logging:
            logger.info("Camera %d auto-remuxing video with corrected FPS...", self.camera_id)
            remuxed_path = auto_remux_recording(self.video_path, replace_original=True)
            if remuxed_path:
                logger.info("Camera %d recording saved with corrected FPS: %s", self.camera_id, remuxed_path)
            else:
                logger.warning("Camera %d remux failed, keeping original: %s", self.camera_id, self.video_path)
        elif self.video_path:
            logger.info("Camera %d recording saved: %s", self.camera_id, self.video_path)

    def cleanup(self) -> None:
        self.stop_recording()

    def submit_frame(self, frame: np.ndarray, metadata: FrameTimingMetadata) -> None:
        if frame is None:
            return

        with self._latest_lock:
            # Accumulate any drops from this frame
            if metadata.dropped_since_last is not None and metadata.dropped_since_last > 0:
                self._accumulated_drops += metadata.dropped_since_last
                self._total_hardware_drops += metadata.dropped_since_last
                # Debug: Log when drops are accumulated
                logger.info("Camera %d: Accumulated %d drops (total now: %d, accumulated now: %d) - hw_frame=%s, sw_frame=%s",
                           self.camera_id, metadata.dropped_since_last,
                           self._total_hardware_drops, self._accumulated_drops,
                           metadata.camera_frame_index, metadata.software_frame_index)

            # Frame is already contiguous from cv2 operations, no need to copy
            self._latest_frame = frame
            self._latest_metadata = metadata

    def _frame_timer_loop(self) -> None:
        if self._frame_interval <= 0:
            return

        while not self._stop_event.is_set():
            next_frame_time = self._next_frame_time
            if next_frame_time is None:
                break

            now = time.perf_counter()
            if next_frame_time > now:
                time.sleep(next_frame_time - now)
                now = time.perf_counter()

            frame_to_write: Optional[np.ndarray]
            metadata: Optional[FrameTimingMetadata]

            with self._latest_lock:
                frame_to_write = self._latest_frame
                metadata = self._latest_metadata
                if frame_to_write is not None:
                    self._latest_frame = None
                    self._latest_metadata = None

            # DROP-ONLY MODE: Skip frames when no new frame available
            if frame_to_write is None:
                self._skipped_frames += 1
                self._next_frame_time = next_frame_time + self._frame_interval
                continue

            if metadata is None:
                metadata = FrameTimingMetadata()  # Empty metadata as fallback

            queued = _QueuedFrame(
                frame=frame_to_write,
                metadata=metadata,
                enqueued_monotonic=time.perf_counter(),
            )

            if self._frame_queue is not None:
                try:
                    self._frame_queue.put(queued, timeout=self._frame_interval)
                except queue.Full:
                    try:
                        _ = self._frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._frame_queue.put_nowait(queued)
                    except queue.Full:
                        self._skipped_frames += 1

            self._next_frame_time = next_frame_time + self._frame_interval

        logger.debug("Camera %d timer loop exited", self.camera_id)

    def _frame_writer_loop(self) -> None:
        """
        OPTIMIZED: Write frames to ffmpeg ONLY. CSV logging happens in separate thread.
        """
        while not self._stop_event.is_set():
            if self._frame_queue is None:
                break
            try:
                queued = self._frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if queued is self._queue_sentinel:
                break

            write_start_monotonic = time.perf_counter()
            write_time_unix = time.time()

            # Write frame to ffmpeg (FAST PATH - no CSV operations)
            self._write_frame_impl(queued.frame)

            write_end_monotonic = time.perf_counter()

            # Queue CSV logging data if enabled (non-blocking)
            # IMPORTANT: Use display_frame_index to match the frame number shown in video overlay
            if self.enable_csv_logging and self._csv_queue is not None:
                backlog_after = self._frame_queue.qsize() if self._frame_queue is not None else 0
                # Use display_frame_index if available, otherwise fall back to written_frames
                frame_number_for_csv = queued.metadata.display_frame_index if queued.metadata.display_frame_index is not None else self._written_frames
                csv_entry = _CSVLogEntry(
                    frame_number=frame_number_for_csv,  # Matches overlay frame number on video
                    write_time_unix=write_time_unix,
                    write_start_monotonic=write_start_monotonic,
                    write_end_monotonic=write_end_monotonic,
                    enqueued_monotonic=queued.enqueued_monotonic,
                    metadata=queued.metadata,
                    backlog_after=backlog_after,
                    last_write_monotonic=self._last_write_monotonic,
                    last_camera_frame_index=self._last_camera_frame_index,
                )
                try:
                    self._csv_queue.put_nowait(csv_entry)
                except queue.Full:
                    # Drop CSV entry if queue full (video writes take priority)
                    pass

            # Increment frame counter AFTER logging (so CSV has 0-indexed frame numbers)
            self._written_frames += 1

            # Update tracking state
            self._last_write_monotonic = write_start_monotonic
            if queued.metadata.camera_frame_index is not None:
                self._last_camera_frame_index = queued.metadata.camera_frame_index

        logger.debug("Camera %d writer loop exited", self.camera_id)

    def _write_frame_impl(self, frame: np.ndarray) -> None:
        """
        OPTIMIZED: Direct frame write to ffmpeg stdin
        """
        if self._ffmpeg_process is None or self._ffmpeg_process.stdin is None:
            return

        target_w, target_h = self.resolution

        # Resize if needed (should be rare)
        if frame.shape[1] != target_w or frame.shape[0] != target_h:
            frame = cv2.resize(frame, (target_w, target_h))

        try:
            # OPTIMIZED: Write directly from numpy array to avoid intermediate copies
            # Using tobytes() is faster than going through bytearray assignment
            frame_bytes = frame.tobytes()

            # Write directly to ffmpeg stdin
            self._ffmpeg_process.stdin.write(frame_bytes)

            # Batch flush: only flush every N frames for better performance
            self._video_write_counter += 1
            if self._video_write_counter >= self._video_flush_interval:
                self._ffmpeg_process.stdin.flush()
                self._video_write_counter = 0
        except Exception:
            logger.exception("Failed to write frame for camera %d", self.camera_id)

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
