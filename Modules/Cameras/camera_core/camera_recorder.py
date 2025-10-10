#!/usr/bin/env python3
"""
Camera recording manager with consistent FPS and detailed timing diagnostics.
Handles video encoding via ffmpeg and frame timing CSV output.
"""

import datetime
import logging
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from .camera_utils import FrameTimingMetadata, _QueuedFrame

logger = logging.getLogger("CameraRecorder")


class CameraRecordingManager:
    """Consistent-FPS recorder with detailed timing diagnostics."""

    def __init__(self, camera_id: int, resolution: tuple[int, int], fps: float):
        self.camera_id = camera_id
        self.resolution = resolution
        self.fps = fps

        self.recording = False
        self.video_path: Optional[Path] = None
        self.frame_timing_path: Optional[Path] = None

        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._frame_timing_file: Optional[Any] = None
        self._frame_queue: Optional[queue.Queue[_QueuedFrame]] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._timer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._queue_sentinel = object()

        self._latest_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_metadata: Optional[FrameTimingMetadata] = None
        self._last_frame_used: Optional[np.ndarray] = None

        self._frame_interval = 1.0 / fps if fps > 0 else 0.0
        self._next_frame_time: Optional[float] = None
        self._written_frames = 0
        self._skipped_frames = 0
        self._duplicated_frames = 0
        self._last_write_monotonic: Optional[float] = None

    @property
    def written_frames(self) -> int:
        return self._written_frames

    @property
    def skipped_frames(self) -> int:
        return self._skipped_frames

    @property
    def duplicated_frames(self) -> int:
        return self._duplicated_frames

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

        self._frame_timing_file = open(self.frame_timing_path, "w", encoding="utf-8")
        self._frame_timing_file.write(
            "frame_number,write_time_unix,write_time_iso,expected_delta,actual_delta,delta_error,"
            "queue_delay,capture_latency,write_duration,queue_backlog_after,camera_frame_index,"
            "display_frame_index,camera_timestamp_unix,camera_timestamp_diff,available_camera_fps,"
            "dropped_frames_total,duplicates_total,is_duplicate\n"
        )

        max_queue = max(int(self.fps * 4), 60)
        self._frame_queue = queue.Queue(max_queue)
        self._stop_event.clear()
        self._next_frame_time = time.perf_counter()
        self._written_frames = 0
        self._skipped_frames = 0
        self._duplicated_frames = 0
        self._last_write_monotonic = None
        self._last_frame_used = None

        self._writer_thread = threading.Thread(target=self._frame_writer_loop, name=f"Cam{self.camera_id}-writer", daemon=True)
        self._writer_thread.start()
        self._timer_thread = threading.Thread(target=self._frame_timer_loop, name=f"Cam{self.camera_id}-timer", daemon=True)
        self._timer_thread.start()

        self.recording = True
        logger.info("Camera %d recording to %s", self.camera_id, self.video_path)

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

        if self._timer_thread is not None:
            self._timer_thread.join(timeout=2.0)
        self._timer_thread = None

        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5.0)
        self._writer_thread = None

        if self._frame_queue is not None:
            while not self._frame_queue.empty():
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    break
        self._frame_queue = None

        if self._ffmpeg_process is not None:
            try:
                self._ffmpeg_process.stdin.close()
                self._ffmpeg_process.wait(timeout=5)
            except Exception:
                self._ffmpeg_process.terminate()
            self._ffmpeg_process = None

        if self._frame_timing_file is not None:
            self._frame_timing_file.flush()
            self._frame_timing_file.close()
            self._frame_timing_file = None

        self._latest_frame = None
        self._latest_metadata = None
        self._last_frame_used = None

        if self.video_path:
            logger.info("Camera %d recording saved: %s", self.camera_id, self.video_path)

    def cleanup(self) -> None:
        self.stop_recording()

    def submit_frame(self, frame: np.ndarray, metadata: FrameTimingMetadata) -> None:
        if frame is None:
            return

        with self._latest_lock:
            self._latest_frame = np.ascontiguousarray(frame)
            metadata.is_duplicate = False
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

            is_duplicate = False
            if frame_to_write is None:
                if self._last_frame_used is None:
                    self._skipped_frames += 1
                    self._next_frame_time = next_frame_time + self._frame_interval
                    continue
                frame_to_write = self._last_frame_used
                metadata = FrameTimingMetadata(
                    requested_fps=self.fps,
                    camera_frame_index=None,
                    is_duplicate=True,
                )
                is_duplicate = True
                self._duplicated_frames += 1

            if metadata is None:
                metadata = FrameTimingMetadata(requested_fps=self.fps)

            self._last_frame_used = frame_to_write

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

            if is_duplicate and metadata is not None:
                metadata.duplicates_total = self._duplicated_frames

        logger.debug("Camera %d timer loop exited", self.camera_id)

    def _frame_writer_loop(self) -> None:
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

            self._write_frame_impl(queued.frame)

            write_end_monotonic = time.perf_counter()
            backlog_after = self._frame_queue.qsize() if self._frame_queue is not None else 0
            self._log_frame_timing(
                queued,
                write_time_unix,
                write_start_monotonic,
                write_end_monotonic,
                backlog_after,
            )

        logger.debug("Camera %d writer loop exited", self.camera_id)

    def _write_frame_impl(self, frame: np.ndarray) -> None:
        if self._ffmpeg_process is None or self._ffmpeg_process.stdin is None:
            return

        target_w, target_h = self.resolution
        if frame.shape[1] != target_w or frame.shape[0] != target_h:
            frame = cv2.resize(frame, (target_w, target_h))

        try:
            self._ffmpeg_process.stdin.write(frame.tobytes())
            self._ffmpeg_process.stdin.flush()
        except Exception:
            logger.exception("Failed to write frame for camera %d", self.camera_id)

    def _log_frame_timing(
        self,
        queued: _QueuedFrame,
        write_time_unix: float,
        write_start_monotonic: float,
        write_end_monotonic: float,
        backlog_after: int,
    ) -> None:
        if self._frame_timing_file is None:
            return

        expected_delta = 1.0 / self.fps if self.fps > 0 else 0.0
        actual_delta = None
        if self._last_write_monotonic is not None:
            actual_delta = write_start_monotonic - self._last_write_monotonic

        delta_error = None
        if actual_delta is not None:
            delta_error = actual_delta - expected_delta

        queue_delay = write_start_monotonic - queued.enqueued_monotonic
        capture_latency = None
        if queued.metadata.capture_monotonic is not None:
            capture_latency = write_start_monotonic - queued.metadata.capture_monotonic

        camera_timestamp_diff = None
        if queued.metadata.capture_unix is not None:
            camera_timestamp_diff = write_time_unix - queued.metadata.capture_unix

        write_duration = write_end_monotonic - write_start_monotonic

        self._written_frames += 1
        self._last_write_monotonic = write_start_monotonic

        write_time_iso = datetime.datetime.fromtimestamp(write_time_unix, tz=datetime.timezone.utc).isoformat(timespec="milliseconds")

        def fmt(value: Optional[float]) -> str:
            return f"{value:.6f}" if value is not None else ""

        row = (
            f"{self._written_frames},{write_time_unix:.6f},{write_time_iso},{fmt(expected_delta)},{fmt(actual_delta)},{fmt(delta_error)},"
            f"{fmt(queue_delay)},{fmt(capture_latency)},{fmt(write_duration)},{backlog_after},"
            f"{queued.metadata.camera_frame_index if queued.metadata.camera_frame_index is not None else ''},"
            f"{queued.metadata.display_frame_index if queued.metadata.display_frame_index is not None else ''},"
            f"{fmt(queued.metadata.capture_unix)},{fmt(camera_timestamp_diff)},{fmt(queued.metadata.available_camera_fps)},"
            f"{queued.metadata.dropped_frames_total if queued.metadata.dropped_frames_total is not None else ''},"
            f"{queued.metadata.duplicates_total if queued.metadata.duplicates_total is not None else ''},"
            f"{1 if queued.metadata.is_duplicate else 0}\n"
        )

        self._frame_timing_file.write(row)
        self._frame_timing_file.flush()
