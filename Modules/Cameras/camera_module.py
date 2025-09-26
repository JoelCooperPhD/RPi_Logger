#!/usr/bin/env python3
import os
import cv2
import logging
import datetime
import argparse
import time
import signal
import sys
import json
import threading
import select
import queue
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

import numpy as np
from picamera2 import Picamera2

# Logging setup - force to stderr for slave mode compatibility
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,  # Force logging to stderr
)
logger = logging.getLogger("CameraSystem")


class RollingFPS:
    """Calculate FPS using a rolling window."""

    def __init__(self, window_seconds: float = 5.0):
        self.window_seconds = window_seconds
        self.frame_timestamps: deque[float] = deque()

    def add_frame(self, timestamp: Optional[float] = None) -> None:
        if timestamp is None:
            timestamp = time.time()
        self.frame_timestamps.append(timestamp)
        cutoff = timestamp - self.window_seconds
        while self.frame_timestamps and self.frame_timestamps[0] < cutoff:
            self.frame_timestamps.popleft()

    def get_fps(self) -> float:
        if len(self.frame_timestamps) < 2:
            return 0.0
        timespan = self.frame_timestamps[-1] - self.frame_timestamps[0]
        if timespan <= 0:
            return 0.0
        return (len(self.frame_timestamps) - 1) / timespan

    def reset(self) -> None:
        self.frame_timestamps.clear()


@dataclass(slots=True)
class FrameTimingMetadata:
    """Per-frame metadata captured for timing diagnostics."""

    capture_monotonic: Optional[float] = None
    capture_unix: Optional[float] = None
    camera_frame_index: Optional[int] = None
    display_frame_index: Optional[int] = None
    dropped_frames_total: Optional[int] = None
    duplicates_total: Optional[int] = None
    available_camera_fps: Optional[float] = None
    requested_fps: Optional[float] = None
    is_duplicate: bool = False


@dataclass(slots=True)
class _QueuedFrame:
    frame: np.ndarray
    metadata: FrameTimingMetadata
    enqueued_monotonic: float


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
class CameraHandler:
    def __init__(self, cam_info, cam_num, args, session_dir: Path):
        self.logger = logging.getLogger(f"Camera{cam_num}")
        self.cam_num = cam_num
        self.args = args
        self.session_dir = Path(session_dir)
        self.output_dir = Path(args.output)
        self.recording = False
        self.recorder: Optional[Path] = None
        self.last_recording: Optional[Path] = None

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info("Initializing camera %d", cam_num)
        self.picam2 = Picamera2(cam_num)

        # Configure recording stream (full resolution, adjustable fps)
        config = self.picam2.create_video_configuration(
            main={
                "size": (args.width, args.height),
                "format": "RGB888",
            },
            controls={
                "FrameDurationLimits": (int(1e6 / args.fps), int(1e6 / args.fps)),
            },
        )
        self.picam2.configure(config)
        self.picam2.start()
        self.logger.info("Camera %d initialized", cam_num)

        self.capture_fps_tracker = RollingFPS(window_seconds=5.0)
        self.display_fps_tracker = RollingFPS(window_seconds=5.0)
        self.recording_manager = CameraRecordingManager(
            camera_id=cam_num,
            resolution=(args.width, args.height),
            fps=float(args.fps),
        )
        self.preview_frame_index = 0
        self.last_sequence: Optional[int] = None
        self.dropped_frames = 0

    def start_recording(self):
        if self.recording:
            return
        self.recording_manager.start_recording(self.session_dir)
        self.recorder = self.recording_manager.video_path
        self.last_recording = self.recorder
        if self.recorder:
            self.logger.info("Recording to %s", self.recorder)
        self.recording = True

    def stop_recording(self):
        if not self.recording:
            return
        self.recording_manager.stop_recording()
        self.last_recording = self.recording_manager.video_path
        if self.recorder:
            self.logger.info("Stopped recording: %s", self.recorder)
        self.recording = False
        self.recorder = None

    def get_frame(self):
        capture_monotonic = time.perf_counter()
        raw_frame = self.picam2.capture_array("main")
        if raw_frame is None:
            return None

        capture_unix = time.time()
        try:
            metadata = self.picam2.capture_metadata() or {}
        except Exception as exc:  # pragma: no cover - defensive
            metadata = {}
            self.logger.debug("Capture metadata unavailable: %s", exc)

        sequence = metadata.get("Sequence")
        if sequence is not None:
            try:
                sequence = int(sequence)
            except (TypeError, ValueError):
                sequence = None

        if sequence is not None and self.last_sequence is not None:
            delta = sequence - self.last_sequence
            if isinstance(delta, int) and delta > 1:
                self.dropped_frames += delta - 1
        if sequence is not None:
            self.last_sequence = sequence

        if raw_frame.ndim == 3 and raw_frame.shape[2] == 3:
            frame_bgr = cv2.cvtColor(raw_frame, cv2.COLOR_RGB2BGR)
        else:
            frame_bgr = raw_frame

        self.preview_frame_index += 1
        self.capture_fps_tracker.add_frame(capture_unix)
        self.display_fps_tracker.add_frame(capture_unix)

        available_fps = self.capture_fps_tracker.get_fps()
        display_fps = self.display_fps_tracker.get_fps()

        frame_metadata = FrameTimingMetadata(
            capture_monotonic=capture_monotonic,
            capture_unix=capture_unix,
            camera_frame_index=sequence,
            display_frame_index=self.preview_frame_index,
            dropped_frames_total=self.dropped_frames,
            duplicates_total=self.recording_manager.duplicated_frames,
            available_camera_fps=available_fps,
            requested_fps=float(self.args.fps),
        )

        if self.recording_manager.is_recording:
            self.recording_manager.submit_frame(frame_bgr, frame_metadata)

        preview_frame = cv2.resize(frame_bgr, (self.args.preview_width, self.args.preview_height))
        self._add_overlays(
            preview_frame,
            available_fps=available_fps,
            display_fps=display_fps,
        )
        return preview_frame

    def _add_overlays(self, frame: np.ndarray, *, available_fps: float, display_fps: float) -> None:
        h, w = frame.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        thickness = 2

        banner_height = min(210, max(160, int(h * 0.35)))
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, banner_height), (255, 255, 255), -1)
        cv2.addWeighted(frame, 0.7, overlay, 0.3, 0, dst=frame)

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line_y = 25
        line_step = 25

        cv2.putText(frame, f"Cam {self.cam_num} | {timestamp}", (10, line_y), font, font_scale, (0, 0, 0), thickness)
        line_y += line_step
        cv2.putText(frame, f"Session: {self.session_dir.name}", (10, line_y), font, font_scale, (0, 0, 0), thickness)
        line_y += line_step
        cv2.putText(frame, f"Requested FPS: {float(self.args.fps):.1f}", (10, line_y), font, font_scale, (0, 0, 0), thickness)
        line_y += line_step
        cv2.putText(frame, f"Sensor FPS: {available_fps:.1f}", (10, line_y), font, font_scale, (0, 0, 0), thickness)
        line_y += line_step
        cv2.putText(frame, f"Display FPS: {display_fps:.1f}", (10, line_y), font, font_scale, (0, 0, 0), thickness)
        line_y += line_step
        cv2.putText(frame, f"Dropped Frames: {self.dropped_frames}", (10, line_y), font, font_scale, (0, 0, 0), thickness)
        line_y += line_step
        cv2.putText(
            frame,
            f"Duplicated Frames: {self.recording_manager.duplicated_frames}",
            (10, line_y),
            font,
            font_scale,
            (0, 0, 0),
            thickness,
        )
        line_y += line_step

        if self.recording_manager.is_recording and self.recorder is not None:
            cv2.putText(frame, "RECORDING", (w - 160, 30), font, font_scale, (0, 0, 255), thickness)
            cv2.putText(
                frame,
                f"Recorded Frames: {self.recording_manager.written_frames}",
                (10, line_y),
                font,
                font_scale,
                (0, 0, 0),
                thickness,
            )
            if line_y + line_step < banner_height:
                cv2.putText(
                    frame,
                    self.recorder.name,
                    (10, line_y + line_step),
                    font,
                    0.5,
                    (0, 0, 0),
                    1,
                )
        else:
            cv2.putText(frame, "Idle", (w - 80, 30), font, font_scale, (0, 0, 0), thickness)

        cv2.rectangle(frame, (0, h - 28), (w, h), (0, 0, 0), -1)
        cv2.putText(
            frame,
            "Q: Quit | R: Record | S: Snapshot",
            (10, h - 8),
            font,
            0.5,
            (255, 255, 255),
            1,
        )

    def cleanup(self):
        self.stop_recording()
        self.recording_manager.cleanup()
        self.picam2.stop()
        self.picam2.close()
        self.logger.info("Cleanup completed")


class CameraSystem:
    def __init__(self, args):
        self.logger = logging.getLogger("CameraSystem")
        self.cameras = []
        self.running = False
        self.recording = False
        self.args = args
        self.slave_mode = args.slave
        self.command_thread = None
        self.shutdown_event = threading.Event()
        self.device_timeout = getattr(args, 'timeout', 5)  # Default 5 seconds timeout
        self.session_dir: Optional[Path] = None
        self.session_label: Optional[str] = None

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Device will be initialized in run() method after signal handlers are ready
        if self.slave_mode:
            self.send_status("initializing", {"device": "cameras"})

    def _ensure_session_dir(self) -> Path:
        if self.session_dir is None:
            timestamp = datetime.datetime.now().strftime("session_%Y%m%d_%H%M%S")
            base = Path(self.args.output)
            self.session_dir = base / timestamp
            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.session_label = self.session_dir.name
            self.logger.info("New recording session directory: %s", self.session_dir)
        return self.session_dir

    def _initialize_cameras(self):
        """Initialize cameras with timeout and graceful handling"""
        self.logger.info("Searching for cameras (timeout: %ds)...", self.device_timeout)

        start_time = time.time()
        cam_infos = []

        # Try to detect cameras with timeout
        while time.time() - start_time < self.device_timeout:
            try:
                cam_infos = Picamera2.global_camera_info()
                if cam_infos:
                    break
            except Exception as e:
                self.logger.debug("Camera detection attempt failed: %s", e)

            # Check if we should abort
            if self.shutdown_event.is_set():
                raise KeyboardInterrupt("Device discovery cancelled")

            time.sleep(0.5)  # Brief pause between attempts

        # Log found cameras
        for i, info in enumerate(cam_infos):
            self.logger.info("Found camera %d: %s", i, info)

        # Check if we have the required cameras
        if not cam_infos:
            error_msg = f"No cameras found within {self.device_timeout} seconds"
            self.logger.error(error_msg)
            if self.slave_mode:
                self.send_status("error", {"message": error_msg})
            raise RuntimeError(error_msg)

        if len(cam_infos) < 2 and not self.args.single_camera:
            warning_msg = f"Only {len(cam_infos)} camera(s) found, expected at least 2"
            self.logger.warning(warning_msg)
            if not self.args.allow_partial:
                if self.slave_mode:
                    self.send_status("error", {"message": warning_msg})
                raise RuntimeError(warning_msg)

        # Initialize available cameras
        self.logger.info("Initializing %d camera(s)...", min(len(cam_infos), 2))
        try:
            session_dir = self._ensure_session_dir()
            for i in range(min(len(cam_infos), 2)):
                self.cameras.append(CameraHandler(cam_infos[i], i, self.args, session_dir))

            self.logger.info("Successfully initialized %d camera(s)", len(self.cameras))
            if self.slave_mode:
                self.send_status(
                    "initialized",
                    {"cameras": len(self.cameras), "session": self.session_label},
                )

        except Exception as e:
            self.logger.error("Failed to initialize cameras: %s", e)
            if self.slave_mode:
                self.send_status("error", {"message": f"Camera initialization failed: {e}"})
            raise

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info("Received signal %d, shutting down...", signum)
        self.running = False
        self.shutdown_event.set()
        if self.slave_mode:
            self.send_status("shutdown", {"signal": signum})

    def send_status(self, status_type, data=None):
        """Send status message to master (if in slave mode)"""
        if not self.slave_mode:
            return

        message = {
            "type": "status",
            "status": status_type,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data or {}
        }
        # Force to stdout for master communication
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    def handle_command(self, command_data):
        """Handle command from master"""
        try:
            cmd = command_data.get("command")

            if cmd == "start_recording":
                if not self.recording:
                    self._ensure_session_dir()
                    for cam in self.cameras:
                        cam.start_recording()
                    self.recording = True
                    self.send_status(
                        "recording_started",
                        {
                            "session": self.session_label,
                            "files": [str(cam.recorder) for cam in self.cameras if cam.recorder],
                        },
                    )
                else:
                    self.send_status("error", {"message": "Already recording"})

            elif cmd == "stop_recording":
                if self.recording:
                    for cam in self.cameras:
                        cam.stop_recording()
                    self.recording = False
                    self.send_status(
                        "recording_stopped",
                        {
                            "session": self.session_label,
                            "files": [
                                str(cam.last_recording)
                                for cam in self.cameras
                                if cam.last_recording is not None
                            ],
                        },
                    )
                else:
                    self.send_status("error", {"message": "Not recording"})

            elif cmd == "take_snapshot":
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filenames = []
                for i, cam in enumerate(self.cameras):
                    frame = cam.get_frame()
                    if frame is not None:
                        filename = os.path.join(self.args.output, f"snapshot_cam{i}_{ts}.jpg")
                        cv2.imwrite(filename, frame)
                        filenames.append(filename)
                self.send_status("snapshot_taken", {"files": filenames})

            elif cmd == "get_status":
                status_data = {
                    "recording": self.recording,
                    "session": self.session_label,
                    "cameras": [
                        {
                            "cam_num": cam.cam_num,
                            "recording": cam.recording,
                            "sensor_fps": round(cam.capture_fps_tracker.get_fps(), 2),
                            "display_frames": cam.preview_frame_index,
                            "dropped_frames": cam.dropped_frames,
                            "duplicated_frames": cam.recording_manager.duplicated_frames,
                            "recorded_frames": cam.recording_manager.written_frames,
                            "output": str(cam.recorder) if cam.recorder else None,
                        } for cam in self.cameras
                    ]
                }
                self.send_status("status_report", status_data)

            elif cmd == "quit":
                self.running = False
                self.shutdown_event.set()
                self.send_status("quitting")

            else:
                self.send_status("error", {"message": f"Unknown command: {cmd}"})

        except Exception as e:
            self.send_status("error", {"message": str(e)})

    def command_listener(self):
        """Listen for commands from stdin in slave mode"""
        while self.running and not self.shutdown_event.is_set():
            try:
                # Use select to check if stdin has data available
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    line = sys.stdin.readline().strip()
                    if line:
                        command_data = json.loads(line)
                        self.handle_command(command_data)
            except json.JSONDecodeError as e:
                self.send_status("error", {"message": f"Invalid JSON: {e}"})
            except Exception as e:
                self.send_status("error", {"message": f"Command error: {e}"})
                break

    def preview_loop(self):
        """Interactive preview mode (standalone only)"""
        if not self.cameras:
            self.logger.error("No cameras available for preview")
            return

        self.running = True

        # Create windows for available cameras
        for i, cam in enumerate(self.cameras):
            cv2.namedWindow(f"Camera {i}")

        self.logger.info("Preview mode: 'q' to quit, 's' for snapshot, 'r' to toggle recording")
        while self.running and not self.shutdown_event.is_set():
            frames = [cam.get_frame() for cam in self.cameras]

            # Display frames for available cameras
            for i, frame in enumerate(frames):
                if frame is not None:
                    cv2.imshow(f"Camera {i}", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                self.running = False
            elif key == ord("r"):
                if not self.recording:
                    for cam in self.cameras:
                        cam.start_recording()
                    self.recording = True
                else:
                    for cam in self.cameras:
                        cam.stop_recording()
                    self.recording = False
            elif key == ord("s"):
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                for i, frame in enumerate(frames):
                    if frame is not None:
                        filename = os.path.join(self.args.output, f"snapshot_cam{i}_{ts}.jpg")
                        cv2.imwrite(filename, frame)
                        self.logger.info("Saved snapshot %s", filename)

        self.logger.info("All preview windows closed")
        cv2.destroyAllWindows()

    def slave_loop(self):
        """Command-driven slave mode (no GUI)"""
        self.running = True

        # Start command listener thread
        self.command_thread = threading.Thread(target=self.command_listener, daemon=True)
        self.command_thread.start()

        self.logger.info("Slave mode: waiting for commands...")

        # Keep cameras active but don't display
        while self.running and not self.shutdown_event.is_set():
            # Just keep cameras running and capture frames to maintain FPS calculation
            for cam in self.cameras:
                cam.get_frame()  # This updates FPS counters

            # Brief sleep to prevent excessive CPU usage
            time.sleep(0.033)  # ~30 FPS update rate

        self.logger.info("Slave mode ended")

    def run(self):
        """Main run method - chooses mode based on configuration"""
        try:
            # Initialize cameras now that signal handlers are set up
            self._initialize_cameras()

            if self.slave_mode:
                self.slave_loop()
            else:
                self.preview_loop()

        except KeyboardInterrupt:
            self.logger.info("Camera system cancelled by user")
            if self.slave_mode:
                self.send_status("error", {"message": "Cancelled by user"})
        except RuntimeError as e:
            # Device not found or initialization failed - already logged
            pass
        except Exception as e:
            self.logger.error("Unexpected error in run: %s", e)
            if self.slave_mode:
                self.send_status("error", {"message": f"Unexpected error: {e}"})

    def cleanup(self):
        self.logger.info("Cleaning up cameras...")
        for cam in self.cameras:
            cam.cleanup()
        self.logger.info("Cleanup completed")


def parse_args():
    parser = argparse.ArgumentParser(description="Multi-camera recorder with preview and overlays")
    parser.add_argument("--width", type=int, default=1920, help="Recording width")
    parser.add_argument("--height", type=int, default=1080, help="Recording height")
    parser.add_argument("--fps", type=int, default=30, help="Recording FPS")
    parser.add_argument("--preview-width", type=int, default=640, help="Preview window width")
    parser.add_argument("--preview-height", type=int, default=360, help="Preview window height")
    parser.add_argument("--output", type=str, default="recordings", help="Output directory")
    parser.add_argument("--slave", action="store_true", help="Run in slave mode (no preview, command-driven)")
    parser.add_argument("--timeout", type=int, default=5, help="Device discovery timeout in seconds (default: 5)")
    parser.add_argument("--single-camera", action="store_true", help="Allow running with single camera")
    parser.add_argument("--allow-partial", action="store_true", help="Allow running with fewer cameras than expected")
    return parser.parse_args()


def main():
    args = parse_args()
    system = None
    try:
        system = CameraSystem(args)
        system.run()
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        if system and system.slave_mode:
            system.send_status("error", {"message": f"Fatal error: {e}"})
    finally:
        if system:
            system.cleanup()


if __name__ == "__main__":
    main()
