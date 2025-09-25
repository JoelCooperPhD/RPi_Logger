#!/usr/bin/env python3
"""
Recording Manager for Gaze Tracker
Handles video recording using FFmpeg and logs frame timing diagnostics.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Any, TextIO

import cv2
import numpy as np

from config import Config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FrameTimingMetadata:
    """Metadata captured for each frame write used in frame timing diagnostics."""

    capture_monotonic: Optional[float] = None
    capture_unix: Optional[float] = None
    camera_frame_index: Optional[int] = None
    display_frame_index: Optional[int] = None
    dropped_frames_total: Optional[int] = None
    duplicates_total: Optional[int] = None
    available_camera_fps: Optional[float] = None
    requested_fps: Optional[float] = None
    gaze_timestamp: Optional[float] = None
    is_duplicate: Optional[bool] = None


@dataclass(slots=True)
class _QueuedFrame:
    frame: np.ndarray
    enqueued_monotonic: float
    metadata: FrameTimingMetadata


class RecordingManager:
    """Manages video recording functionality"""

    def __init__(self, config: Config, *, use_ffmpeg: bool = True):
        self.config = config
        self.recording = False
        self.ffmpeg_process: Optional[subprocess.Popen] = None
        self.recording_filename: Optional[str] = None
        self.gaze_filename: Optional[str] = None
        self.frame_timing_filename: Optional[str] = None

        self._gaze_file: Optional[TextIO] = None
        self._frame_timing_file: Optional[TextIO] = None
        self._last_gaze_timestamp: Optional[float] = None
        self._last_write_monotonic: Optional[float] = None
        self._written_frames = 0
        self._skipped_frames = 0  # Frames skipped due to FPS throttling
        self._duplicated_frames = 0  # Frames duplicated when no new frame available
        self._recording_start_time: Optional[float] = None
        self._next_frame_time: Optional[float] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_frame_metadata: Optional[FrameTimingMetadata] = None
        self._frame_timer_task: Optional[asyncio.Task] = None

        self.use_ffmpeg = use_ffmpeg
        self._opencv_writer: Optional[cv2.VideoWriter] = None
        self._frame_queue: Optional[asyncio.Queue[Any]] = None
        self._frame_writer_task: Optional[asyncio.Task] = None
        self._queue_sentinel: object = object()
        self._gaze_queue: Optional[asyncio.Queue[str]] = None
        self._gaze_writer_task: Optional[asyncio.Task] = None
        self._gaze_queue_sentinel: object = object()

        # Ensure output directory exists
        os.makedirs(config.output_dir, exist_ok=True)

    async def toggle_recording(self):
        """Toggle recording on/off"""
        if self.recording:
            await self.stop_recording()
        else:
            await self.start_recording()

    async def start_recording(self):
        """Start FFmpeg recording"""
        if self.recording:
            return

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        w, h = self.config.resolution
        self.recording_filename = os.path.join(
            self.config.output_dir,
            f"gaze_{w}x{h}_{self.config.fps}fps_{timestamp}.mp4"
        )
        self.gaze_filename = os.path.join(
            self.config.output_dir,
            f"gaze_{w}x{h}_{self.config.fps}fps_{timestamp}.csv"
        )
        self.frame_timing_filename = os.path.join(
            self.config.output_dir,
            f"gaze_{w}x{h}_{self.config.fps}fps_{timestamp}_frame_timing.csv"
        )

        try:
            if self.use_ffmpeg:
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
                    "bgr24",
                    "-r",
                    str(self.config.fps),
                    "-i",
                    "-",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "23",
                    self.recording_filename,
                ]

                self.ffmpeg_process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdin=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
            else:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                self._opencv_writer = cv2.VideoWriter(
                    self.recording_filename,
                    fourcc,
                    self.config.fps,
                    (w, h),
                )
                if not self._opencv_writer.isOpened():
                    raise RuntimeError("Failed to start OpenCV video writer")

            self._gaze_file = open(self.gaze_filename, "w", encoding="utf-8")
            self._gaze_file.write("timestamp,x,y,worn\n")
            self._frame_timing_file = open(self.frame_timing_filename, "w", encoding="utf-8")
            self._frame_timing_file.write(
                "frame_number,write_time_unix,write_time_iso,expected_delta,actual_delta,delta_error,"
                "queue_delay,capture_latency,write_duration,queue_backlog_after,camera_frame_index,"
                "display_frame_index,camera_timestamp_unix,camera_timestamp_diff,gaze_timestamp_unix,"
                "gaze_timestamp_diff,available_camera_fps,dropped_frames_total,duplicates_total,is_duplicate\n"
            )

            self._last_gaze_timestamp = None
            self._last_write_monotonic = None
            self._written_frames = 0
            self._skipped_frames = 0
            self._duplicated_frames = 0
            self._recording_start_time = time.perf_counter()
            self._next_frame_time = self._recording_start_time
            self._latest_frame = None
            self._latest_frame_metadata = None
            self.recording = True

            max_video_queue = max(int(self.config.fps * 2), 30)
            self._frame_queue = asyncio.Queue(maxsize=max_video_queue)
            self._gaze_queue = asyncio.Queue(maxsize=512)
            self._frame_writer_task = asyncio.create_task(self._frame_writer_loop())
            self._gaze_writer_task = asyncio.create_task(self._gaze_writer_loop())
            self._frame_timer_task = asyncio.create_task(self._frame_timer_loop())
            logger.info("Recording started: %s", self.recording_filename)
        except Exception as exc:
            logger.error("Failed to start recording: %s", exc)
            await self._handle_start_failure()

    async def _handle_start_failure(self) -> None:
        if self.ffmpeg_process:
            with contextlib.suppress(Exception):
                self.ffmpeg_process.terminate()
        self.ffmpeg_process = None
        if self._opencv_writer is not None:
            self._opencv_writer.release()
        self._opencv_writer = None
        if self._gaze_file:
            self._gaze_file.close()
        self._gaze_file = None
        if self._frame_timing_file:
            self._frame_timing_file.close()
        self._frame_timing_file = None
        self.gaze_filename = None
        self.frame_timing_filename = None
        if self._frame_writer_task:
            self._frame_writer_task.cancel()
        self._frame_writer_task = None
        self._frame_queue = None
        if self._gaze_writer_task:
            self._gaze_writer_task.cancel()
        self._gaze_writer_task = None
        self._gaze_queue = None

        if self._frame_timer_task:
            self._frame_timer_task.cancel()
        self._frame_timer_task = None
        self.recording = False

    async def stop_recording(self):
        """Stop FFmpeg recording"""
        if not self.recording and self.ffmpeg_process is None and self._gaze_file is None:
            return

        self.recording = False

        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.stdin.close()
                self.ffmpeg_process.wait(timeout=5)
            except Exception:  # pragma: no cover - defensive
                self.ffmpeg_process.terminate()
            finally:
                self.ffmpeg_process = None

        if self._opencv_writer is not None:
            self._opencv_writer.release()
            self._opencv_writer = None

        if self._frame_queue is not None:
            try:
                await self._frame_queue.put(self._queue_sentinel)
            except RuntimeError:
                self._frame_queue.put_nowait(self._queue_sentinel)

        if self._frame_writer_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._frame_writer_task
        self._frame_writer_task = None
        self._frame_queue = None

        if self._gaze_queue is not None:
            try:
                await self._gaze_queue.put(self._gaze_queue_sentinel)
            except RuntimeError:
                self._gaze_queue.put_nowait(self._gaze_queue_sentinel)

        if self._gaze_writer_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._gaze_writer_task
        self._gaze_writer_task = None
        self._gaze_queue = None

        if self._gaze_file:
            try:
                self._gaze_file.flush()
            finally:
                self._gaze_file.close()
                self._gaze_file = None
            logger.info("Gaze data saved: %s", self.gaze_filename)

        if self._frame_timing_file:
            self._frame_timing_file.flush()
            self._frame_timing_file.close()
            self._frame_timing_file = None
            logger.info("Frame timing saved: %s", self.frame_timing_filename)

        self._last_gaze_timestamp = None
        self._last_write_monotonic = None
        self._written_frames = 0
        self._skipped_frames = 0
        self._duplicated_frames = 0
        self._recording_start_time = None
        self._next_frame_time = None
        self._latest_frame = None
        self._latest_frame_metadata = None

        if self.recording_filename:
            logger.info("Recording saved: %s", self.recording_filename)

    def write_frame(self, frame: np.ndarray, metadata: Optional[FrameTimingMetadata] = None):
        """Update the latest frame available for timed recording"""
        if not self.recording:
            return

        # Store the latest frame and metadata - timer loop will use this
        self._latest_frame = frame.copy()  # Make a copy to avoid race conditions
        metadata = metadata or FrameTimingMetadata(requested_fps=self.config.fps)
        metadata.is_duplicate = False  # This is a new frame
        self._latest_frame_metadata = metadata

    def write_gaze_sample(self, gaze: Optional[Any]):
        """Write gaze data sample to CSV if recording."""
        if not self.recording or self._gaze_file is None or gaze is None:
            return

        timestamp = getattr(gaze, "timestamp_unix_seconds", None)
        if timestamp is not None and timestamp == self._last_gaze_timestamp:
            return

        try:
            x = getattr(gaze, "x", float("nan"))
            y = getattr(gaze, "y", float("nan"))
            worn = getattr(gaze, "worn", False)
            line = f"{timestamp if timestamp is not None else ''},{x},{y},{int(bool(worn))}\n"
        except Exception as exc:
            logger.error("Failed to write gaze sample: %s", exc)
        else:
            self._last_gaze_timestamp = timestamp
            if self._gaze_queue is None:
                self._gaze_file.write(line)
                self._gaze_file.flush()
            else:
                try:
                    self._gaze_queue.put_nowait(line)
                except asyncio.QueueFull:
                    with contextlib.suppress(asyncio.QueueEmpty):
                        _ = self._gaze_queue.get_nowait()
                    self._gaze_queue.put_nowait(line)

    @property
    def is_recording(self) -> bool:
        """Check if currently recording"""
        return self.recording

    @property
    def skipped_frames(self) -> int:
        """Get count of frames skipped due to FPS throttling"""
        return self._skipped_frames

    @property
    def duplicated_frames(self) -> int:
        """Get count of frames duplicated for exact timing"""
        return self._duplicated_frames

    async def cleanup(self):
        """Clean up recording resources"""
        await self.stop_recording()

    async def _frame_writer_loop(self) -> None:
        assert self._frame_queue is not None
        while True:
            queued = await self._frame_queue.get()
            if queued is self._queue_sentinel:
                break
            if not isinstance(queued, _QueuedFrame):
                continue

            write_start_monotonic = time.perf_counter()
            write_time_unix = time.time()
            backlog_after = self._frame_queue.qsize()

            if self.use_ffmpeg:
                await asyncio.to_thread(self._write_frame_impl, queued.frame)
            else:
                self._write_frame_impl(queued.frame)

            write_end_monotonic = time.perf_counter()
            self._log_frame_timing(queued, write_time_unix, write_start_monotonic, write_end_monotonic, backlog_after)

    def _write_frame_impl(self, frame: np.ndarray) -> None:
        w, h = self.config.resolution
        if frame.shape[:2] != (h, w):
            frame = cv2.resize(frame, (w, h))

        frame_data = np.ascontiguousarray(frame)

        if self.use_ffmpeg:
            if not self.ffmpeg_process or self.ffmpeg_process.poll() is not None:
                return
            try:
                self.ffmpeg_process.stdin.write(frame_data.tobytes())
                self.ffmpeg_process.stdin.flush()
            except Exception:  # pragma: no cover - defensive
                pass
        else:
            if self._opencv_writer is not None:
                self._opencv_writer.write(frame_data)

    async def _gaze_writer_loop(self) -> None:
        assert self._gaze_queue is not None
        buffer: list[str] = []
        flush_threshold = 32
        while True:
            line = await self._gaze_queue.get()
            if line is self._gaze_queue_sentinel:
                break
            buffer.append(line)
            if len(buffer) >= flush_threshold:
                await asyncio.to_thread(self._flush_gaze_lines, buffer)
                buffer.clear()

        if buffer:
            await asyncio.to_thread(self._flush_gaze_lines, buffer)

    def _flush_gaze_lines(self, lines: list[str]) -> None:
        if self._gaze_file is None:
            return
        self._gaze_file.writelines(lines)
        self._gaze_file.flush()

    async def _frame_timer_loop(self) -> None:
        """Timer-based frame writing loop that ensures exact FPS and video duration"""
        if self.config.fps <= 0:
            return

        frame_interval = 1.0 / self.config.fps
        last_frame_used = None

        while self.recording and self._frame_queue is not None:
            current_time = time.perf_counter()

            # Wait until it's time for the next frame
            if self._next_frame_time > current_time:
                sleep_time = self._next_frame_time - current_time
                await asyncio.sleep(sleep_time)
                current_time = time.perf_counter()

            # Get the frame to write (latest or duplicate last)
            frame_to_write = None
            is_duplicate = False
            write_time_unix = time.time()

            if self._latest_frame is not None:
                # New frame available
                frame_to_write = self._latest_frame.copy()
                metadata = self._latest_frame_metadata
                last_frame_used = frame_to_write
            elif last_frame_used is not None:
                # No new frame - duplicate the last one
                frame_to_write = last_frame_used.copy()
                metadata = FrameTimingMetadata(
                    capture_monotonic=None,  # This is a duplicate, no new capture time
                    capture_unix=None,       # This is a duplicate, no new capture time
                    requested_fps=self.config.fps,
                    is_duplicate=True,
                    # Copy other metadata that might be relevant
                    camera_frame_index=getattr(self._latest_frame_metadata, 'camera_frame_index', None) if self._latest_frame_metadata else None,
                )
                is_duplicate = True
                self._duplicated_frames += 1
            else:
                # No frame available at all - skip this time slot
                self._skipped_frames += 1
                self._next_frame_time += frame_interval
                continue

            # Queue the frame for writing
            queued = _QueuedFrame(
                frame=frame_to_write,
                enqueued_monotonic=current_time,
                metadata=metadata,
            )

            try:
                self._frame_queue.put_nowait(queued)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    _ = self._frame_queue.get_nowait()
                self._frame_queue.put_nowait(queued)

            # Advance to next frame time (exact intervals)
            self._next_frame_time += frame_interval

            # Clear the latest frame after using it (to detect new vs duplicate)
            if not is_duplicate:
                self._latest_frame = None

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

        expected_delta = 1.0 / self.config.fps if self.config.fps > 0 else 0.0
        actual_delta: Optional[float] = None
        if self._last_write_monotonic is not None:
            actual_delta = write_start_monotonic - self._last_write_monotonic

        delta_error: Optional[float] = None
        if actual_delta is not None:
            delta_error = actual_delta - expected_delta

        queue_delay = write_start_monotonic - queued.enqueued_monotonic

        capture_latency: Optional[float] = None
        if queued.metadata.capture_monotonic is not None:
            capture_latency = write_start_monotonic - queued.metadata.capture_monotonic

        camera_timestamp_diff: Optional[float] = None
        if queued.metadata.capture_unix is not None:
            camera_timestamp_diff = write_time_unix - queued.metadata.capture_unix

        gaze_timestamp_diff: Optional[float] = None
        if queued.metadata.gaze_timestamp is not None:
            gaze_timestamp_diff = write_time_unix - queued.metadata.gaze_timestamp

        write_duration = write_end_monotonic - write_start_monotonic

        self._written_frames += 1
        self._last_write_monotonic = write_start_monotonic

        write_time_iso = datetime.datetime.fromtimestamp(write_time_unix, tz=datetime.timezone.utc).isoformat(
            timespec="milliseconds"
        )

        def fmt(value: Optional[float]) -> str:
            return f"{value:.6f}" if value is not None else ""

        row = (
            f"{self._written_frames},{write_time_unix:.6f},{write_time_iso},{fmt(expected_delta)},{fmt(actual_delta)},{fmt(delta_error)},"
            f"{fmt(queue_delay)},{fmt(capture_latency)},{fmt(write_duration)},{backlog_after},"
            f"{queued.metadata.camera_frame_index if queued.metadata.camera_frame_index is not None else ''},"
            f"{queued.metadata.display_frame_index if queued.metadata.display_frame_index is not None else ''},"
            f"{fmt(queued.metadata.capture_unix)},{fmt(camera_timestamp_diff)},{fmt(queued.metadata.gaze_timestamp)},{fmt(gaze_timestamp_diff)},"
            f"{fmt(queued.metadata.available_camera_fps)},{queued.metadata.dropped_frames_total if queued.metadata.dropped_frames_total is not None else ''},"
            f"{queued.metadata.duplicates_total if queued.metadata.duplicates_total is not None else ''},"
            f"{1 if queued.metadata.is_duplicate else 0}\n"
        )

        self._frame_timing_file.write(row)
        self._frame_timing_file.flush()
