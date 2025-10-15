#!/usr/bin/env python3
"""
Recording Manager for Gaze Tracker
Handles video recording using FFmpeg and logs frame timing diagnostics.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import datetime
import io
import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any, TextIO

import cv2
import numpy as np

# Import TrackerConfig from parent package
from ..config.tracker_config import TrackerConfig as Config

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
        self.imu_filename: Optional[str] = None
        self.events_filename: Optional[str] = None

        self._gaze_file: Optional[TextIO] = None
        self._frame_timing_file: Optional[TextIO] = None
        self._imu_file: Optional[TextIO] = None
        self._event_file: Optional[TextIO] = None
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
        self._imu_queue: Optional[asyncio.Queue[str]] = None
        self._imu_writer_task: Optional[asyncio.Task] = None
        self._imu_queue_sentinel: object = object()
        self._event_queue: Optional[asyncio.Queue[str]] = None
        self._event_writer_task: Optional[asyncio.Task] = None
        self._event_queue_sentinel: object = object()

        self._output_root = Path(config.output_dir)
        self._output_root.mkdir(parents=True, exist_ok=True)
        self._current_experiment_dir: Optional[Path] = None
        self._current_experiment_started_at: Optional[datetime.datetime] = None
        self._recordings_this_experiment = 0
        self._current_experiment_label: Optional[str] = None

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
        target_dir = self._current_experiment_dir or self._output_root
        target_dir.mkdir(parents=True, exist_ok=True)

        base_name = f"gaze_{w}x{h}_{self.config.fps}fps_{timestamp}"
        self.recording_filename = str(target_dir / f"{base_name}.mp4")
        self.gaze_filename = str(target_dir / f"{base_name}.csv")
        self.frame_timing_filename = str(target_dir / f"{base_name}_frame_timing.csv")
        self.imu_filename = str(target_dir / f"{base_name}_imu.csv")
        self.events_filename = str(target_dir / f"{base_name}_events.csv")

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
            self._imu_file = open(self.imu_filename, "w", encoding="utf-8")
            self._imu_file.write(
                "timestamp,timestamp_ns,gyro_x,gyro_y,gyro_z,accel_x,accel_y,accel_z,"
                "quat_w,quat_x,quat_y,quat_z,temperature\n"
            )
            self._event_file = open(self.events_filename, "w", encoding="utf-8")
            self._event_file.write(
                "timestamp,timestamp_ns,event_type,event_subtype,confidence,duration,payload\n"
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
            self._imu_queue = asyncio.Queue(maxsize=1024)
            self._event_queue = asyncio.Queue(maxsize=512)
            self._frame_writer_task = asyncio.create_task(self._frame_writer_loop())
            self._gaze_writer_task = asyncio.create_task(self._gaze_writer_loop())
            self._imu_writer_task = asyncio.create_task(self._imu_writer_loop())
            self._event_writer_task = asyncio.create_task(self._event_writer_loop())
            self._frame_timer_task = asyncio.create_task(self._frame_timer_loop())
            logger.info("Recording started: %s", self.recording_filename)
            if self._current_experiment_dir is not None:
                self._recordings_this_experiment += 1
                logger.info(
                    "Experiment '%s' recordings so far: %d",
                    self._current_experiment_dir.name,
                    self._recordings_this_experiment,
                )
        except Exception as exc:
            logger.error("Failed to start recording: %s", exc)
            await self._handle_start_failure()

    def start_experiment(self, label: Optional[str] = None) -> Path:
        """Create a new experiment directory under the output root."""
        if self.recording:
            raise RuntimeError("Stop the active recording before starting a new experiment")

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = None
        if label:
            candidate = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label.strip())
            candidate = candidate.strip("-_")
            if candidate:
                safe_label = candidate.lower()

        folder_name = f"experiment_{timestamp}"
        if safe_label:
            folder_name = f"{folder_name}_{safe_label}"

        experiment_dir = self._output_root / folder_name
        experiment_dir.mkdir(parents=True, exist_ok=True)

        self._current_experiment_dir = experiment_dir
        self._current_experiment_started_at = datetime.datetime.now()
        self._current_experiment_label = folder_name
        self._recordings_this_experiment = 0

        logger.info("Started new experiment: %s", experiment_dir)
        return experiment_dir

    @property
    def current_experiment_dir(self) -> Optional[Path]:
        return self._current_experiment_dir

    @property
    def current_experiment_label(self) -> Optional[str]:
        return self._current_experiment_label

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
        if self._imu_file:
            self._imu_file.close()
        self._imu_file = None
        if self._event_file:
            self._event_file.close()
        self._event_file = None
        self.gaze_filename = None
        self.frame_timing_filename = None
        self.imu_filename = None
        self.events_filename = None
        if self._frame_writer_task:
            self._frame_writer_task.cancel()
        self._frame_writer_task = None
        self._frame_queue = None
        if self._gaze_writer_task:
            self._gaze_writer_task.cancel()
        self._gaze_writer_task = None
        self._gaze_queue = None
        if self._imu_writer_task:
            self._imu_writer_task.cancel()
        self._imu_writer_task = None
        self._imu_queue = None
        if self._event_writer_task:
            self._event_writer_task.cancel()
        self._event_writer_task = None
        self._event_queue = None

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

        if self._imu_queue is not None:
            try:
                await self._imu_queue.put(self._imu_queue_sentinel)
            except RuntimeError:
                self._imu_queue.put_nowait(self._imu_queue_sentinel)

        if self._imu_writer_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._imu_writer_task
        self._imu_writer_task = None
        self._imu_queue = None

        if self._event_queue is not None:
            try:
                await self._event_queue.put(self._event_queue_sentinel)
            except RuntimeError:
                self._event_queue.put_nowait(self._event_queue_sentinel)

        if self._event_writer_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._event_writer_task
        self._event_writer_task = None
        self._event_queue = None

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

        if self._imu_file:
            try:
                self._imu_file.flush()
            finally:
                self._imu_file.close()
                self._imu_file = None
            logger.info("IMU data saved: %s", self.imu_filename)

        if self._event_file:
            try:
                self._event_file.flush()
            finally:
                self._event_file.close()
                self._event_file = None
            logger.info("Eye events saved: %s", self.events_filename)

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
            fields = [
                self._stringify(timestamp),
                self._stringify(x),
                self._stringify(y),
                self._stringify(int(bool(worn))),
            ]
            line = self._compose_csv_line(fields)
        except Exception as exc:
            logger.error("Failed to write gaze sample: %s", exc)
        else:
            self._last_gaze_timestamp = timestamp
            self._enqueue_csv_line(self._gaze_queue, self._gaze_file, line)

    def write_imu_sample(self, imu: Optional[Any]):
        """Write IMU sample (gyro/accel/orientation) to CSV if recording."""
        if not self.recording or self._imu_file is None or imu is None:
            return

        timestamp = getattr(imu, "timestamp_unix_seconds", None)
        timestamp_ns = getattr(imu, "timestamp_unix_ns", None)

        gyro = self._extract_components(getattr(imu, "gyro_data", None), ("x", "y", "z"), 3)
        accel = self._extract_components(getattr(imu, "accel_data", None), ("x", "y", "z"), 3)
        quaternion = self._extract_components(getattr(imu, "quaternion", None), ("w", "x", "y", "z"), 4)
        temperature = getattr(imu, "temperature", None)

        fields = [
            self._stringify(timestamp),
            self._stringify(timestamp_ns),
            *gyro,
            *accel,
            *quaternion,
            self._stringify(temperature),
        ]
        line = self._compose_csv_line(fields)
        self._enqueue_csv_line(self._imu_queue, self._imu_file, line)

    def write_event_sample(self, event: Optional[Any]):
        """Write eye event sample (fixation/saccade/blink) to CSV if recording."""
        if not self.recording or self._event_file is None or event is None:
            return

        timestamp = getattr(event, "timestamp_unix_seconds", None)
        timestamp_ns = getattr(event, "timestamp_unix_ns", None)

        event_type = getattr(event, "type", None) or getattr(event, "event_type", None)
        subtype = getattr(event, "category", None) or getattr(event, "event_subtype", None)
        confidence = getattr(event, "confidence", None)
        duration = getattr(event, "duration", None)

        payload = self._event_payload_as_json(event)

        fields = [
            self._stringify(timestamp),
            self._stringify(timestamp_ns),
            self._stringify(event_type),
            self._stringify(subtype),
            self._stringify(confidence),
            self._stringify(duration),
            payload,
        ]
        line = self._compose_csv_line(fields)
        self._enqueue_csv_line(self._event_queue, self._event_file, line)

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            text = f"{value:.9f}"
            return text.rstrip("0").rstrip(".") if "." in text else text
        return str(value)

    def _extract_components(self, source: Any, preferred_attr_order: tuple[str, ...], expected_len: int) -> list[str]:
        """Return stringified vector components preserving attribute ordering when possible."""
        blanks = [""] * expected_len
        if source is None:
            return blanks

        values: list[Any] = []

        if isinstance(source, dict):
            for attr in preferred_attr_order:
                if attr in source:
                    values.append(source[attr])
        else:
            for attr in preferred_attr_order:
                if hasattr(source, attr):
                    values.append(getattr(source, attr))

        if not values:
            try:
                if isinstance(source, (list, tuple)):
                    values = list(source)
                else:
                    values = list(source)  # type: ignore[arg-type]
            except TypeError:
                values = [source]

        for idx in range(min(expected_len, len(values))):
            blanks[idx] = self._stringify(values[idx])

        return blanks

    def _event_payload_as_json(self, event: Any) -> str:
        """Serialize event attributes as JSON for traceability."""
        if event is None:
            return ""

        payload: dict[str, Any] = {}
        for attr in dir(event):
            if attr.startswith("_"):
                continue
            try:
                value = getattr(event, attr)
            except Exception:  # pragma: no cover - defensive
                continue
            if callable(value):
                continue
            payload[attr] = value

        if not payload:
            return ""

        try:
            return json.dumps(payload, default=str)
        except TypeError:
            safe_payload = {k: str(v) for k, v in payload.items()}
            return json.dumps(safe_payload)

    def _compose_csv_line(self, fields: list[str]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="")
        writer.writerow(fields)
        return buffer.getvalue() + "\n"

    def _enqueue_csv_line(
        self,
        queue: Optional[asyncio.Queue[str]],
        file_obj: Optional[TextIO],
        line: str,
    ) -> None:
        if file_obj is None:
            return
        if queue is None:
            file_obj.write(line)
            file_obj.flush()
            return
        try:
            queue.put_nowait(line)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                _ = queue.get_nowait()
            queue.put_nowait(line)

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
                await asyncio.to_thread(self._flush_lines, self._gaze_file, buffer)
                buffer.clear()

        if buffer:
            await asyncio.to_thread(self._flush_lines, self._gaze_file, buffer)

    async def _imu_writer_loop(self) -> None:
        assert self._imu_queue is not None
        buffer: list[str] = []
        flush_threshold = 128
        while True:
            line = await self._imu_queue.get()
            if line is self._imu_queue_sentinel:
                break
            buffer.append(line)
            if len(buffer) >= flush_threshold:
                await asyncio.to_thread(self._flush_lines, self._imu_file, buffer)
                buffer.clear()

        if buffer:
            await asyncio.to_thread(self._flush_lines, self._imu_file, buffer)

    async def _event_writer_loop(self) -> None:
        assert self._event_queue is not None
        buffer: list[str] = []
        flush_threshold = 64
        while True:
            line = await self._event_queue.get()
            if line is self._event_queue_sentinel:
                break
            buffer.append(line)
            if len(buffer) >= flush_threshold:
                await asyncio.to_thread(self._flush_lines, self._event_file, buffer)
                buffer.clear()

        if buffer:
            await asyncio.to_thread(self._flush_lines, self._event_file, buffer)

    def _flush_lines(self, file_obj: Optional[TextIO], lines: list[str]) -> None:
        if file_obj is None or not lines:
            return
        file_obj.writelines(lines)
        file_obj.flush()

    async def _frame_timer_loop(self) -> None:
        """Timer-based frame writing loop that ensures exact FPS and video duration"""
        if self.config.fps <= 0:
            return

        frame_interval = 1.0 / self.config.fps
        last_frame_used = None

        while True:
            if not self.recording:
                break

            frame_queue = self._frame_queue
            if frame_queue is None:
                break

            next_frame_time = self._next_frame_time
            if next_frame_time is None:
                break

            current_time = time.perf_counter()

            # Wait until it's time for the next frame
            if next_frame_time > current_time:
                sleep_time = next_frame_time - current_time
                await asyncio.sleep(sleep_time)
                current_time = time.perf_counter()
                next_frame_time = self._next_frame_time
                if next_frame_time is None:
                    break

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
            if metadata is None:
                metadata = FrameTimingMetadata(requested_fps=self.config.fps)
            queued = _QueuedFrame(
                frame=frame_to_write,
                enqueued_monotonic=current_time,
                metadata=metadata,
            )

            try:
                frame_queue.put_nowait(queued)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    _ = frame_queue.get_nowait()
                frame_queue.put_nowait(queued)

            # Advance to next frame time (exact intervals)
            next_frame_time = self._next_frame_time
            if next_frame_time is None:
                break
            self._next_frame_time = next_frame_time + frame_interval

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
