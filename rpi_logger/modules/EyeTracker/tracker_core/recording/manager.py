
from __future__ import annotations

import asyncio
import contextlib
import csv
import datetime
import io
import json
import logging
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any, TextIO, TYPE_CHECKING

import numpy as np

from rpi_logger.modules.base.recording import RecordingManagerBase
from rpi_logger.modules.base.storage_utils import (
    ensure_module_data_dir,
    module_filename_prefix,
)
from rpi_logger.core.logging_utils import get_module_logger
from ..config.tracker_config import TrackerConfig as Config
from .async_csv_writer import AsyncCSVWriter
from .video_encoder import VideoEncoder
from pupil_labs.realtime_api.models import ConnectionType, SensorName, Status

if TYPE_CHECKING:
    from pupil_labs.realtime_api.streaming import AudioFrame
    from ..device_manager import DeviceManager

logger = get_module_logger(__name__)


@dataclass(slots=True)
class FrameTimingMetadata:

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


class RecordingManager(RecordingManagerBase):

    MODULE_SUBDIR_NAME = "EyeTracker-Neon"

    def __init__(self, config: Config, *, use_ffmpeg: bool = True, device_manager: Optional["DeviceManager"] = None):
        super().__init__(device_id="eye_tracker")
        self.config = config
        self.device_manager = device_manager
        self.recording_filename: Optional[str] = None
        self.gaze_filename: Optional[str] = None
        self.frame_timing_filename: Optional[str] = None
        self.imu_filename: Optional[str] = None
        self.events_filename: Optional[str] = None
        self.advanced_gaze_filename: Optional[str] = None
        self.audio_filename: Optional[str] = None
        self.audio_timing_filename: Optional[str] = None
        self.device_status_filename: Optional[str] = None
        self.eyes_video_filename: Optional[str] = None
        self.eyes_timing_filename: Optional[str] = None

        self._frame_timing_file: Optional[TextIO] = None
        self._timing_rows_since_flush: int = 0
        self._last_gaze_timestamp: Optional[float] = None
        self._last_write_monotonic: Optional[float] = None
        self._written_frames = 0
        self._recorded_frame_count = 0  # Frame counter for overlay (matches CSV frame_number)
        self._skipped_frames = 0  # Frames skipped due to FPS throttling
        self._duplicated_frames = 0  # Frames duplicated when no new frame available
        self._recording_start_time: Optional[float] = None
        self._next_frame_time: Optional[float] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_frame_metadata: Optional[FrameTimingMetadata] = None
        self._frame_timer_task: Optional[asyncio.Task] = None

        self.use_ffmpeg = use_ffmpeg
        self._video_encoder = VideoEncoder(config.resolution, config.fps, use_ffmpeg=use_ffmpeg)
        self._frame_queue: Optional[asyncio.Queue[Any]] = None
        self._frame_writer_task: Optional[asyncio.Task] = None
        self._queue_sentinel: object = object()

        self._gaze_writer: Optional[AsyncCSVWriter] = None
        self._gaze_full_writer: Optional[AsyncCSVWriter] = None
        self._imu_writer: Optional[AsyncCSVWriter] = None
        self._event_writer: Optional[AsyncCSVWriter] = None
        self._audio_timing_writer: Optional[AsyncCSVWriter] = None
        self._device_status_writer: Optional[AsyncCSVWriter] = None

        self._audio_frame_queue: Optional[asyncio.Queue[Any]] = None
        self._audio_writer_task: Optional[asyncio.Task] = None
        self._audio_queue_sentinel: object = object()
        self._device_status_task: Optional[asyncio.Task] = None

        # Eyes video recording
        self._eyes_video_encoder: Optional[VideoEncoder] = None
        self._eyes_frame_queue: Optional[asyncio.Queue[Any]] = None
        self._eyes_writer_task: Optional[asyncio.Task] = None
        self._eyes_queue_sentinel: object = object()
        self._eyes_timing_writer: Optional[AsyncCSVWriter] = None
        self._eyes_frames_written = 0

        self._imu_samples_written = 0
        self._event_samples_written = 0

        self._output_root = Path(config.output_dir)
        self._output_root.mkdir(parents=True, exist_ok=True)
        self._current_experiment_dir: Optional[Path] = None
        self._current_experiment_started_at: Optional[datetime.datetime] = None
        self._recordings_this_experiment = 0
        self._current_experiment_label: Optional[str] = None

    async def toggle_recording(self):
        if self._is_recording:
            await self.stop_recording()
        else:
            await self.start_recording()

    def set_session_context(
        self,
        session_dir: Path,
        trial_number: int = 1,
        *,
        trial_label: str = ""
    ):
        """Set session context for recording.

        Args:
            session_dir: Directory for session data (module subdir already applied by caller)
            trial_number: Current trial number
            trial_label: Optional experiment/condition label
        """
        # Session dir should already be the module subdirectory from runtime
        module_dir = self._ensure_module_subdir(session_dir)
        super().set_session_context(module_dir, trial_number)
        self._current_experiment_label = trial_label or None

    async def start_recording(self, session_dir: Optional[Path] = None, trial_number: int = 1) -> Path:
        if self._is_recording:
            if self.recording_filename:
                return Path(self.recording_filename)
            raise RuntimeError("Already recording but no filename set")

        # Use provided session_dir or fall back to experiment dir or output root
        if session_dir is not None:
            target_dir = self._ensure_module_subdir(session_dir)
        else:
            target_dir = self._current_experiment_dir
            if target_dir is None:
                target_dir = self._ensure_module_subdir(self._output_root)
            else:
                target_dir.mkdir(parents=True, exist_ok=True)

        self._current_session_dir = target_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        self._current_trial_number = trial_number

        w, h = self.config.resolution
        prefix = module_filename_prefix(
            target_dir,
            self.MODULE_SUBDIR_NAME,
            trial_number,
            code="ET",
        )
        self.recording_filename = str(
            target_dir / f"{prefix}_GAZE_{w}x{h}_{self.config.fps}fps.mp4"
        )

        self.gaze_filename = str(target_dir / f"{prefix}_GAZEDATA.csv")
        self.frame_timing_filename = str(target_dir / f"{prefix}_FRAME.csv")
        self.imu_filename = str(target_dir / f"{prefix}_IMU.csv")
        self.events_filename = str(target_dir / f"{prefix}_EVENT.csv")
        self.advanced_gaze_filename = (
            str(target_dir / f"{prefix}_GAZE.csv")
            if self.config.enable_advanced_gaze_logging
            else None
        )
        # Audio recording always enabled when stream available
        self.audio_filename = str(target_dir / f"{prefix}_AUDIO.wav")
        self.audio_timing_filename = str(target_dir / f"{prefix}_AUDIO_TIMING.csv")
        # Device status logging always enabled when device_manager available
        self.device_status_filename = (
            str(target_dir / f"{prefix}_DEVICESTATUS.csv")
            if self.device_manager is not None
            else None
        )
        # Eyes video: 384x192 combined left+right @ ~200Hz from Neon
        self.eyes_video_filename = str(target_dir / f"{prefix}_EYES_384x192.mp4")
        self.eyes_timing_filename = str(target_dir / f"{prefix}_EYES_TIMING.csv")

        try:
            await self._video_encoder.start(Path(self.recording_filename))

            frame_timing_path = Path(self.frame_timing_filename)
            frame_timing_exists = await asyncio.to_thread(frame_timing_path.exists)
            self._frame_timing_file = await asyncio.to_thread(
                open,
                frame_timing_path,
                "a" if frame_timing_exists else "w",
                encoding="utf-8",
            )
            if not frame_timing_exists:
                await asyncio.to_thread(
                    self._frame_timing_file.write,
                    "frame_number,write_time_unix,queue_delay,capture_latency,write_duration,queue_backlog_after,"
                    "camera_frame_index,display_frame_index,camera_timestamp_unix,gaze_timestamp_unix,"
                    "available_camera_fps,dropped_frames_total,duplicates_total,is_duplicate\n",
                )

            self._gaze_writer = AsyncCSVWriter(
                header="timestamp,x,y,worn",
                flush_threshold=32,
                queue_size=512,
            )
            await self._gaze_writer.start(Path(self.gaze_filename))

            if self.advanced_gaze_filename:
                self._gaze_full_writer = AsyncCSVWriter(
                    header=(
                        "timestamp,timestamp_ns,stream_type,worn,x,y,"
                        "left_x,left_y,right_x,right_y,"
                        "pupil_diameter_left,pupil_diameter_right,"
                        "eyeball_center_left_x,eyeball_center_left_y,eyeball_center_left_z,"
                        "optical_axis_left_x,optical_axis_left_y,optical_axis_left_z,"
                        "eyeball_center_right_x,eyeball_center_right_y,eyeball_center_right_z,"
                        "optical_axis_right_x,optical_axis_right_y,optical_axis_right_z,"
                        "eyelid_angle_top_left,eyelid_angle_bottom_left,eyelid_aperture_left,"
                        "eyelid_angle_top_right,eyelid_angle_bottom_right,eyelid_aperture_right"
                    ),
                    flush_threshold=32,
                    queue_size=512,
                )
                await self._gaze_full_writer.start(Path(self.advanced_gaze_filename))

            self._imu_writer = AsyncCSVWriter(
                header=(
                    "timestamp,timestamp_ns,gyro_x,gyro_y,gyro_z,accel_x,accel_y,accel_z,"
                    "quat_w,quat_x,quat_y,quat_z,temperature"
                ),
                flush_threshold=128,
                queue_size=1024,
            )
            await self._imu_writer.start(Path(self.imu_filename))

            event_header = "timestamp,timestamp_ns,event_type,event_subtype,confidence,duration,payload"
            if self.config.expand_eye_event_details:
                event_header += (
                    ",start_time_ns,end_time_ns,rtp_timestamp,"
                    "start_gaze_x,start_gaze_y,end_gaze_x,end_gaze_y,"
                    "mean_gaze_x,mean_gaze_y,amplitude_pixels,amplitude_angle_deg,"
                    "mean_velocity,max_velocity"
                )

            self._event_writer = AsyncCSVWriter(
                header=event_header,
                flush_threshold=64,
                queue_size=512,
            )
            await self._event_writer.start(Path(self.events_filename))

            # Audio recording always started (stream availability determines data)
            self._audio_frame_queue = asyncio.Queue(maxsize=max(int(self.config.fps * 6), 240))
            self._audio_writer_task = asyncio.create_task(self._audio_writer_loop())

            self._audio_timing_writer = AsyncCSVWriter(
                header="timestamp,timestamp_ns,sample_rate,num_samples,channels",
                flush_threshold=64,
                queue_size=512,
            )
            await self._audio_timing_writer.start(Path(self.audio_timing_filename))

            if self.device_status_filename:
                self._device_status_writer = AsyncCSVWriter(
                    header=(
                        "timestamp,timestamp_ns,battery_percent,battery_state,memory_bytes,memory_state,"
                        "recording_action,recording_id,recording_duration_seconds,"
                        "hardware_version,glasses_serial,module_serial,"
                        "world_connected,gaze_connected,imu_connected,audio_connected"
                    ),
                    flush_threshold=8,
                    queue_size=256,
                )
                await self._device_status_writer.start(Path(self.device_status_filename))
                self._device_status_task = asyncio.create_task(self._device_status_loop())

            # Eyes video recording (384x192 @ ~200Hz - high frame rate requires larger queue)
            self._eyes_video_encoder = VideoEncoder(
                (384, 192),  # Fixed resolution for Neon eyes camera
                fps=30.0,    # Downsample from 200Hz to 30fps for manageable file size
                use_ffmpeg=self.use_ffmpeg,
            )
            await self._eyes_video_encoder.start(Path(self.eyes_video_filename))

            self._eyes_timing_writer = AsyncCSVWriter(
                header="frame_number,timestamp_unix,timestamp_ns,write_time_unix",
                flush_threshold=64,
                queue_size=1024,
            )
            await self._eyes_timing_writer.start(Path(self.eyes_timing_filename))

            # Eyes stream is ~200Hz, use larger queue to handle bursts
            self._eyes_frame_queue = asyncio.Queue(maxsize=120)
            self._eyes_writer_task = asyncio.create_task(self._eyes_writer_loop())
            self._eyes_frames_written = 0

            self._last_gaze_timestamp = None
            self._last_write_monotonic = None
            self._written_frames = 0
            self._recorded_frame_count = 0
            self._skipped_frames = 0
            self._duplicated_frames = 0
            self._imu_samples_written = 0
            self._event_samples_written = 0
            self._timing_rows_since_flush = 0
            self._recording_start_time = time.perf_counter()
            self._next_frame_time = self._recording_start_time
            self._latest_frame = None
            self._latest_frame_metadata = None
            self._is_recording = True

            max_video_queue = max(int(self.config.fps * 2), 30)
            self._frame_queue = asyncio.Queue(maxsize=max_video_queue)
            self._frame_writer_task = asyncio.create_task(self._frame_writer_loop())
            # Phase 3.1: Use appropriate frame selection based on config
            if self.config.frame_selection_mode == "camera":
                self._frame_timer_task = asyncio.create_task(self._frame_camera_loop())
            else:
                self._frame_timer_task = asyncio.create_task(self._frame_timer_loop())
            logger.info("Recording started: %s", self.recording_filename)
            if self._current_experiment_dir is not None:
                self._recordings_this_experiment += 1
                logger.info(
                    "Experiment '%s' recordings so far: %d",
                    self._current_experiment_dir.name,
                    self._recordings_this_experiment,
                )
            return Path(self.recording_filename)
        except Exception as exc:
            logger.error("Failed to start recording: %s", exc)
            await self._handle_start_failure()
            raise

    def start_experiment(self, label: Optional[str] = None) -> Path:
        if self._is_recording:
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
        await self._video_encoder.cleanup()

        if self._frame_timing_file:
            await asyncio.to_thread(self._frame_timing_file.close)
            self._frame_timing_file = None

        if self._gaze_writer:
            await self._gaze_writer.cleanup()
            self._gaze_writer = None

        if self._gaze_full_writer:
            await self._gaze_full_writer.cleanup()
            self._gaze_full_writer = None

        if self._imu_writer:
            await self._imu_writer.cleanup()
            self._imu_writer = None

        if self._event_writer:
            await self._event_writer.cleanup()
            self._event_writer = None

        if self._audio_timing_writer:
            await self._audio_timing_writer.cleanup()
            self._audio_timing_writer = None

        if self._device_status_writer:
            await self._device_status_writer.cleanup()
            self._device_status_writer = None

        if self._eyes_video_encoder:
            await self._eyes_video_encoder.cleanup()
            self._eyes_video_encoder = None

        if self._eyes_timing_writer:
            await self._eyes_timing_writer.cleanup()
            self._eyes_timing_writer = None

        self.gaze_filename = None
        self.frame_timing_filename = None
        self.imu_filename = None
        self.events_filename = None
        self.advanced_gaze_filename = None
        self.audio_filename = None
        self.audio_timing_filename = None
        self.device_status_filename = None
        self.eyes_video_filename = None
        self.eyes_timing_filename = None
        self._imu_samples_written = 0
        self._event_samples_written = 0
        self._eyes_frames_written = 0
        if self._frame_writer_task:
            self._frame_writer_task.cancel()
        self._frame_writer_task = None
        self._frame_queue = None

        if self._frame_timer_task:
            self._frame_timer_task.cancel()
        self._frame_timer_task = None
        if self._audio_writer_task:
            self._audio_writer_task.cancel()
        self._audio_writer_task = None
        self._audio_frame_queue = None
        if self._device_status_task:
            self._device_status_task.cancel()
        self._device_status_task = None
        if self._eyes_writer_task:
            self._eyes_writer_task.cancel()
        self._eyes_writer_task = None
        self._eyes_frame_queue = None
        self._is_recording = False

    async def stop_recording(self) -> dict:
        if not self._is_recording and not self._video_encoder.is_running() and self._gaze_writer is None:
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
        frames_duplicated = self._duplicated_frames
        output_files = []

        self._is_recording = False

        await self._video_encoder.stop()

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
        if self._gaze_writer:
            await self._gaze_writer.stop()
            logger.info("Gaze data saved: %s", self.gaze_filename)
            if self.gaze_filename:
                output_files.append(Path(self.gaze_filename))
            self._gaze_writer = None

        if self._gaze_full_writer:
            await self._gaze_full_writer.stop()
            logger.info("Advanced gaze data saved: %s", self.advanced_gaze_filename)
            if self.advanced_gaze_filename:
                output_files.append(Path(self.advanced_gaze_filename))
            self._gaze_full_writer = None

        if self._frame_timing_file:
            await asyncio.to_thread(self._frame_timing_file.flush)
            await asyncio.to_thread(self._frame_timing_file.close)
            self._frame_timing_file = None
            logger.info("Frame timing saved: %s", self.frame_timing_filename)
            if self.frame_timing_filename:
                output_files.append(Path(self.frame_timing_filename))

        if self._imu_writer:
            await self._imu_writer.stop()
            logger.info("IMU data saved (%d samples): %s", self._imu_samples_written, self.imu_filename)
            if self.imu_filename:
                output_files.append(Path(self.imu_filename))
            self._imu_writer = None

        if self._event_writer:
            await self._event_writer.stop()
            logger.info("Eye events saved (%d samples): %s", self._event_samples_written, self.events_filename)
            if self.events_filename:
                output_files.append(Path(self.events_filename))
            self._event_writer = None

        if self._audio_frame_queue is not None:
            try:
                self._audio_frame_queue.put_nowait(self._audio_queue_sentinel)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._audio_frame_queue.get_nowait()
                self._audio_frame_queue.put_nowait(self._audio_queue_sentinel)

        if self._audio_writer_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._audio_writer_task
        self._audio_writer_task = None
        if self.audio_filename and Path(self.audio_filename).exists():
            logger.info("Audio saved: %s", self.audio_filename)
            output_files.append(Path(self.audio_filename))
        elif self.audio_filename:
            logger.info("No audio frames captured; skipping %s", self.audio_filename)
        self._audio_frame_queue = None

        if self._audio_timing_writer:
            await self._audio_timing_writer.stop()
            logger.info("Audio timing saved: %s", self.audio_timing_filename)
            if self.audio_timing_filename:
                output_files.append(Path(self.audio_timing_filename))
            self._audio_timing_writer = None

        if self._device_status_task is not None:
            self._device_status_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._device_status_task
        self._device_status_task = None

        if self._device_status_writer:
            await self._device_status_writer.stop()
            logger.info("Device status saved: %s", self.device_status_filename)
            if self.device_status_filename:
                output_files.append(Path(self.device_status_filename))
            self._device_status_writer = None

        # Stop eyes video recording
        if self._eyes_frame_queue is not None:
            try:
                self._eyes_frame_queue.put_nowait(self._eyes_queue_sentinel)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._eyes_frame_queue.get_nowait()
                self._eyes_frame_queue.put_nowait(self._eyes_queue_sentinel)

        if self._eyes_writer_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._eyes_writer_task
        self._eyes_writer_task = None
        self._eyes_frame_queue = None

        if self._eyes_video_encoder is not None:
            await self._eyes_video_encoder.stop()
            if self.eyes_video_filename and Path(self.eyes_video_filename).exists():
                logger.info("Eyes video saved (%d frames): %s", self._eyes_frames_written, self.eyes_video_filename)
                output_files.append(Path(self.eyes_video_filename))
            elif self.eyes_video_filename:
                logger.info("No eyes frames captured; skipping %s", self.eyes_video_filename)
            self._eyes_video_encoder = None

        if self._eyes_timing_writer:
            await self._eyes_timing_writer.stop()
            logger.info("Eyes timing saved: %s", self.eyes_timing_filename)
            if self.eyes_timing_filename:
                output_files.append(Path(self.eyes_timing_filename))
            self._eyes_timing_writer = None

        self._last_gaze_timestamp = None
        self._last_write_monotonic = None
        self._written_frames = 0
        self._recorded_frame_count = 0
        self._skipped_frames = 0
        self._duplicated_frames = 0
        self._imu_samples_written = 0
        self._event_samples_written = 0
        self._eyes_frames_written = 0
        self._recording_start_time = None
        self._next_frame_time = None
        self._latest_frame = None
        self._latest_frame_metadata = None

        if self.recording_filename:
            logger.info("Recording saved: %s", self.recording_filename)
            output_files.insert(0, Path(self.recording_filename))  # Video file first

        return {
            'duration_seconds': duration,
            'frames_written': frames_written,
            'frames_dropped': self._skipped_frames,
            'output_files': output_files,
        }

    async def pause_recording(self):
        raise NotImplementedError("Pause not supported by eye tracker recording")

    async def resume_recording(self):
        raise NotImplementedError("Resume not supported by eye tracker recording")

    def write_frame(self, frame: np.ndarray, metadata: Optional[FrameTimingMetadata] = None):
        if not self._is_recording:
            return

        self._latest_frame = frame  # Reference only - assume ownership/immutability
        metadata = metadata or FrameTimingMetadata(requested_fps=self.config.fps)
        metadata.is_duplicate = False  # This is a new frame
        self._latest_frame_metadata = metadata

    def write_gaze_sample(self, gaze: Optional[Any]):
        if not self._is_recording or self._gaze_writer is None or gaze is None:
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
            self._gaze_writer.enqueue(line)

        if self._gaze_full_writer is not None and gaze is not None:
            detailed_line = self._advanced_gaze_csv_line(gaze)
            if detailed_line is not None:
                self._gaze_full_writer.enqueue(detailed_line)

    def write_imu_sample(self, imu: Optional[Any]):
        if not self._is_recording or self._imu_writer is None or imu is None:
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
        self._imu_writer.enqueue(line)
        self._imu_samples_written += 1
        if self._imu_samples_written == 1:
            logger.info("First IMU sample recorded at %s", self._stringify(timestamp))

    def write_event_sample(self, event: Optional[Any]):
        if not self._is_recording or self._event_writer is None or event is None:
            return

        timestamp = getattr(event, "timestamp_unix_seconds", None)
        timestamp_ns = getattr(event, "timestamp_unix_ns", None)

        event_type = getattr(event, "type", None) or getattr(event, "event_type", None)
        subtype = getattr(event, "category", None) or getattr(event, "event_subtype", None)
        confidence = getattr(event, "confidence", None)

        # Pupil Labs FixationEventData has start_time_ns/end_time_ns but no 'duration'
        # attribute - calculate it if not directly available
        duration = getattr(event, "duration", None)
        if duration is None:
            start_ns = getattr(event, "start_time_ns", None)
            end_ns = getattr(event, "end_time_ns", None)
            if start_ns is not None and end_ns is not None:
                duration = (end_ns - start_ns) / 1e9  # Convert ns to seconds

        payload = self._event_payload_as_json(event)

        start_time_ns = getattr(event, "start_time_ns", None)
        end_time_ns = getattr(event, "end_time_ns", None)
        rtp_timestamp = getattr(event, "rtp_ts_unix_seconds", None)
        start_gaze_x = getattr(event, "start_gaze_x", None)
        start_gaze_y = getattr(event, "start_gaze_y", None)
        end_gaze_x = getattr(event, "end_gaze_x", None)
        end_gaze_y = getattr(event, "end_gaze_y", None)
        mean_gaze_x = getattr(event, "mean_gaze_x", None)
        mean_gaze_y = getattr(event, "mean_gaze_y", None)
        amplitude_pixels = getattr(event, "amplitude_pixels", None)
        amplitude_angle_deg = getattr(event, "amplitude_angle_deg", None)
        mean_velocity = getattr(event, "mean_velocity", None)
        max_velocity = getattr(event, "max_velocity", None)

        fields = [
            self._stringify(timestamp),
            self._stringify(timestamp_ns),
            self._stringify(event_type),
            self._stringify(subtype),
            self._stringify(confidence),
            self._stringify(duration),
            payload,
        ]
        if self.config.expand_eye_event_details:
            fields.extend(
                [
                    self._stringify(start_time_ns),
                    self._stringify(end_time_ns),
                    self._stringify(rtp_timestamp),
                    self._stringify(start_gaze_x),
                    self._stringify(start_gaze_y),
                    self._stringify(end_gaze_x),
                    self._stringify(end_gaze_y),
                    self._stringify(mean_gaze_x),
                    self._stringify(mean_gaze_y),
                    self._stringify(amplitude_pixels),
                    self._stringify(amplitude_angle_deg),
                    self._stringify(mean_velocity),
                    self._stringify(max_velocity),
                ]
            )
        line = self._compose_csv_line(fields)
        self._event_writer.enqueue(line)
        self._event_samples_written += 1
        if self._event_samples_written == 1:
            logger.info("First eye event recorded at %s", self._stringify(timestamp))

    def write_audio_sample(self, audio: Optional["AudioFrame"]):
        if not self._is_recording or self._audio_frame_queue is None or audio is None:
            return

        try:
            self._audio_frame_queue.put_nowait(audio)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._audio_frame_queue.get_nowait()
            self._audio_frame_queue.put_nowait(audio)

    def write_eyes_frame(
        self,
        frame: Optional[np.ndarray],
        timestamp_unix: Optional[float] = None,
        timestamp_ns: Optional[int] = None,
    ):
        """Queue an eyes frame for recording.

        Args:
            frame: BGR numpy array (384x192 for Neon)
            timestamp_unix: Unix timestamp in seconds
            timestamp_ns: Unix timestamp in nanoseconds
        """
        if not self._is_recording:
            return
        if self._eyes_frame_queue is None:
            logger.warning("Eyes frame queue is None while recording")
            return
        if frame is None:
            return

        queued = {
            "frame": frame,
            "timestamp_unix": timestamp_unix,
            "timestamp_ns": timestamp_ns,
            "enqueued_time": time.time(),
        }

        try:
            self._eyes_frame_queue.put_nowait(queued)
        except asyncio.QueueFull:
            # Drop oldest frame to make room
            with contextlib.suppress(asyncio.QueueEmpty):
                self._eyes_frame_queue.get_nowait()
            self._eyes_frame_queue.put_nowait(queued)

        # Debug: log first queued frame
        if not hasattr(self, '_eyes_first_queued_logged'):
            self._eyes_first_queued_logged = True
            logger.info("First eyes frame queued for recording (shape: %s)", frame.shape if hasattr(frame, 'shape') else 'unknown')

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            text = f"{value:.9f}"
            return text.rstrip("0").rstrip(".") if "." in text else text
        return str(value)

    def _extract_components(self, source: Any, preferred_attr_order: tuple[str, ...], expected_len: int) -> list[str]:
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

    def _advanced_gaze_csv_line(self, gaze: Any) -> Optional[str]:
        try:
            timestamp = getattr(gaze, "timestamp_unix_seconds", None)
            timestamp_ns = getattr(gaze, "timestamp_unix_ns", None)
            stream_type = type(gaze).__name__
            worn_attr = getattr(gaze, "worn", None)
            worn_value = int(bool(worn_attr)) if worn_attr is not None else None

            x = getattr(gaze, "x", None)
            y = getattr(gaze, "y", None)

            left_x = left_y = right_x = right_y = None
            left_point = getattr(gaze, "left", None)
            if left_point is not None:
                left_x = getattr(left_point, "x", None)
                left_y = getattr(left_point, "y", None)
            right_point = getattr(gaze, "right", None)
            if right_point is not None:
                right_x = getattr(right_point, "x", None)
                right_y = getattr(right_point, "y", None)

            pupil_diameter_left = getattr(gaze, "pupil_diameter_left", None)
            pupil_diameter_right = getattr(gaze, "pupil_diameter_right", None)

            eyeball_center_left_x = getattr(gaze, "eyeball_center_left_x", None)
            eyeball_center_left_y = getattr(gaze, "eyeball_center_left_y", None)
            eyeball_center_left_z = getattr(gaze, "eyeball_center_left_z", None)
            optical_axis_left_x = getattr(gaze, "optical_axis_left_x", None)
            optical_axis_left_y = getattr(gaze, "optical_axis_left_y", None)
            optical_axis_left_z = getattr(gaze, "optical_axis_left_z", None)

            eyeball_center_right_x = getattr(gaze, "eyeball_center_right_x", None)
            eyeball_center_right_y = getattr(gaze, "eyeball_center_right_y", None)
            eyeball_center_right_z = getattr(gaze, "eyeball_center_right_z", None)
            optical_axis_right_x = getattr(gaze, "optical_axis_right_x", None)
            optical_axis_right_y = getattr(gaze, "optical_axis_right_y", None)
            optical_axis_right_z = getattr(gaze, "optical_axis_right_z", None)

            eyelid_angle_top_left = getattr(gaze, "eyelid_angle_top_left", None)
            eyelid_angle_bottom_left = getattr(gaze, "eyelid_angle_bottom_left", None)
            eyelid_aperture_left = getattr(gaze, "eyelid_aperture_left", None)
            eyelid_angle_top_right = getattr(gaze, "eyelid_angle_top_right", None)
            eyelid_angle_bottom_right = getattr(gaze, "eyelid_angle_bottom_right", None)
            eyelid_aperture_right = getattr(gaze, "eyelid_aperture_right", None)

            fields = [
                self._stringify(timestamp),
                self._stringify(timestamp_ns),
                self._stringify(stream_type),
                self._stringify(worn_value),
                self._stringify(x),
                self._stringify(y),
                self._stringify(left_x),
                self._stringify(left_y),
                self._stringify(right_x),
                self._stringify(right_y),
                self._stringify(pupil_diameter_left),
                self._stringify(pupil_diameter_right),
                self._stringify(eyeball_center_left_x),
                self._stringify(eyeball_center_left_y),
                self._stringify(eyeball_center_left_z),
                self._stringify(optical_axis_left_x),
                self._stringify(optical_axis_left_y),
                self._stringify(optical_axis_left_z),
                self._stringify(eyeball_center_right_x),
                self._stringify(eyeball_center_right_y),
                self._stringify(eyeball_center_right_z),
                self._stringify(optical_axis_right_x),
                self._stringify(optical_axis_right_y),
                self._stringify(optical_axis_right_z),
                self._stringify(eyelid_angle_top_left),
                self._stringify(eyelid_angle_bottom_left),
                self._stringify(eyelid_aperture_left),
                self._stringify(eyelid_angle_top_right),
                self._stringify(eyelid_angle_bottom_right),
                self._stringify(eyelid_aperture_right),
            ]
            return self._compose_csv_line(fields)
        except Exception as exc:
            logger.error("Failed to serialize advanced gaze sample: %s", exc)
            return None

    def _compose_csv_line(self, fields: list[str]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="")
        writer.writerow(fields)
        return buffer.getvalue() + "\n"

    @property
    def skipped_frames(self) -> int:
        return self._skipped_frames

    @property
    def duplicated_frames(self) -> int:
        return self._duplicated_frames

    @property
    def recorded_frame_count(self) -> int:
        return self._recorded_frame_count

    async def cleanup(self):
        await self.stop_recording()

    def get_stats(self) -> dict:
        """Get current recording statistics"""
        duration = 0.0
        if self._is_recording and self._recording_start_time is not None:
            duration = time.perf_counter() - self._recording_start_time

        return {
            'is_recording': self._is_recording,
            'duration_seconds': duration,
            'frames_written': self._written_frames,
            'frames_skipped': self._skipped_frames,
            'frames_duplicated': self._duplicated_frames,
            'recording_filename': self.recording_filename,
            'gaze_filename': self.gaze_filename,
            'advanced_gaze_filename': self.advanced_gaze_filename,
            'frame_timing_filename': self.frame_timing_filename,
            'imu_filename': self.imu_filename,
            'imu_samples_written': self._imu_samples_written,
            'events_filename': self.events_filename,
            'event_samples_written': self._event_samples_written,
            'audio_filename': self.audio_filename,
            'audio_timing_filename': self.audio_timing_filename,
            'device_status_filename': self.device_status_filename,
            'eyes_video_filename': self.eyes_video_filename,
            'eyes_timing_filename': self.eyes_timing_filename,
            'eyes_frames_written': self._eyes_frames_written,
        }

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
                await self._video_encoder.write_frame(queued.frame)
            else:
                self._video_encoder.write_frame(queued.frame)

            write_end_monotonic = time.perf_counter()
            await self._log_frame_timing(queued, write_time_unix, write_start_monotonic, write_end_monotonic, backlog_after)

    async def _audio_writer_loop(self) -> None:
        if self._audio_frame_queue is None or not self.audio_filename:
            return

        wave_file: Optional[wave.Wave_write] = None
        wave_path = Path(self.audio_filename)

        try:
            while True:
                item = await self._audio_frame_queue.get()
                if item is self._audio_queue_sentinel:
                    break
                audio_frame = item

                (
                    sample_rate,
                    channels,
                    pcm_chunks,
                    timestamp,
                    timestamp_ns,
                    sample_count,
                ) = await asyncio.to_thread(self._prepare_audio_frame, audio_frame)

                if not pcm_chunks or sample_rate is None or channels is None:
                    continue

                if wave_file is None:
                    wave_file = await asyncio.to_thread(
                        self._open_wave_file,
                        wave_path,
                        channels,
                        sample_rate,
                    )

                if self._audio_timing_writer is not None:
                    timing_fields = [
                        self._stringify(timestamp),
                        self._stringify(timestamp_ns),
                        self._stringify(sample_rate),
                        self._stringify(sample_count),
                        self._stringify(channels),
                    ]
                    self._audio_timing_writer.enqueue(self._compose_csv_line(timing_fields))

                for chunk in pcm_chunks:
                    await asyncio.to_thread(wave_file.writeframes, chunk)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Audio writer loop failed: %s", exc, exc_info=True)
        finally:
            if wave_file is not None:
                await asyncio.to_thread(wave_file.close)

    async def _eyes_writer_loop(self) -> None:
        """Background task to write eyes frames to video file."""
        if self._eyes_frame_queue is None or self._eyes_video_encoder is None:
            logger.warning("Eyes writer loop: queue or encoder is None, exiting")
            return

        logger.info("Eyes writer loop started")

        # Frame rate limiting: eyes stream is ~200Hz, we downsample to 30fps
        target_fps = 30.0
        min_frame_interval = 1.0 / target_fps
        last_frame_time: Optional[float] = None
        frames_received = 0
        frames_skipped_rate_limit = 0

        try:
            while True:
                item = await self._eyes_frame_queue.get()
                if item is self._eyes_queue_sentinel:
                    logger.info("Eyes writer loop: received sentinel, stopping")
                    break

                frames_received += 1
                frame = item.get("frame")
                timestamp_unix = item.get("timestamp_unix")
                timestamp_ns = item.get("timestamp_ns")

                if frame is None:
                    continue

                # Frame rate limiting
                current_time = time.time()
                if last_frame_time is not None:
                    elapsed = current_time - last_frame_time
                    if elapsed < min_frame_interval:
                        frames_skipped_rate_limit += 1
                        continue  # Skip frame to maintain target fps

                last_frame_time = current_time
                write_time = time.time()

                # Write frame to video
                if self.use_ffmpeg:
                    await self._eyes_video_encoder.write_frame(frame)
                else:
                    self._eyes_video_encoder.write_frame(frame)

                self._eyes_frames_written += 1

                # Log timing data
                if self._eyes_timing_writer is not None:
                    timing_fields = [
                        self._stringify(self._eyes_frames_written),
                        self._stringify(timestamp_unix),
                        self._stringify(timestamp_ns),
                        self._stringify(write_time),
                    ]
                    self._eyes_timing_writer.enqueue(self._compose_csv_line(timing_fields))

                if self._eyes_frames_written == 1:
                    logger.info("First eyes frame recorded (shape: %s)", frame.shape if hasattr(frame, 'shape') else 'unknown')

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Eyes writer loop failed: %s", exc, exc_info=True)
        finally:
            logger.info("Eyes writer loop ended: received=%d, written=%d, skipped_rate_limit=%d",
                       frames_received, self._eyes_frames_written, frames_skipped_rate_limit)

    def _prepare_audio_frame(
        self, audio_frame: "AudioFrame"
    ) -> tuple[Optional[int], Optional[int], list[bytes], Optional[float], Optional[int], int]:
        try:
            sample_rate = getattr(audio_frame.av_frame, "sample_rate", None)
            layout = getattr(audio_frame.av_frame, "layout", None)
            channels = None
            if layout is not None:
                channels = getattr(layout, "nb_channels", None)
                if channels is None:
                    channel_list = getattr(layout, "channels", None)
                    if channel_list is not None:
                        channels = len(channel_list)
            chunks: list[bytes] = []
            total_samples = 0
            last_array: Optional[np.ndarray] = None
            for block in audio_frame.to_resampled_ndarray():
                array = np.asarray(block, dtype=np.int16)
                if array.ndim == 1:
                    array = array.reshape(1, -1)
                total_samples += array.shape[1]
                chunks.append(np.ascontiguousarray(array.T).tobytes())
                last_array = array

            if channels is None and last_array is not None:
                channels = last_array.shape[0]

            timestamp = getattr(audio_frame, "timestamp_unix_seconds", None)
            timestamp_ns = getattr(audio_frame, "timestamp_unix_ns", None)

            return sample_rate, channels, chunks, timestamp, timestamp_ns, total_samples
        except Exception as exc:
            logger.error("Failed to prepare audio frame: %s", exc)
            return None, None, [], None, None, 0

    @staticmethod
    def _open_wave_file(path: Path, channels: int, sample_rate: int) -> wave.Wave_write:
        wave_file = wave.open(str(path), "wb")
        wave_file.setnchannels(channels)
        wave_file.setsampwidth(2)
        wave_file.setframerate(sample_rate)
        return wave_file

    async def _device_status_loop(self) -> None:
        if self.device_manager is None or self._device_status_writer is None:
            return

        interval = max(0.5, float(getattr(self.config, "device_status_poll_interval", 5.0)))

        try:
            while self._is_recording:
                status = await self.device_manager.get_status(force_refresh=True)
                if status is not None:
                    line = self._compose_device_status_line(status)
                    if line:
                        self._device_status_writer.enqueue(line)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Device status loop error: %s", exc)

    def _compose_device_status_line(self, status: Status) -> str:
        now = time.time()
        recording = status.recording
        hardware = status.hardware

        def sensor_connected(name: SensorName) -> bool:
            return any(
                sensor.connected
                for sensor in status.matching_sensors(name, ConnectionType.DIRECT)
            )

        fields = [
            self._stringify(now),
            self._stringify(int(now * 1e9)),
            self._stringify(status.phone.battery_level),
            self._stringify(status.phone.battery_state),
            self._stringify(status.phone.memory),
            self._stringify(status.phone.memory_state),
            self._stringify(getattr(recording, "action", None)),
            self._stringify(getattr(recording, "id", None)),
            self._stringify(getattr(recording, "rec_duration_seconds", None)),
            self._stringify(hardware.version),
            self._stringify(hardware.glasses_serial),
            self._stringify(hardware.module_serial),
            self._stringify(int(sensor_connected(SensorName.WORLD))),
            self._stringify(int(sensor_connected(SensorName.GAZE))),
            self._stringify(int(sensor_connected(SensorName.IMU))),
            self._stringify(int(sensor_connected(SensorName.AUDIO))),
        ]

        return self._compose_csv_line(fields)

    async def _frame_timer_loop(self) -> None:
        if self.config.fps <= 0:
            return

        frame_interval = 1.0 / self.config.fps
        last_frame_used = None

        while True:
            if not self._is_recording:
                break

            frame_queue = self._frame_queue
            if frame_queue is None:
                break

            next_frame_time = self._next_frame_time
            if next_frame_time is None:
                break

            current_time = time.perf_counter()

            if next_frame_time > current_time:
                sleep_time = next_frame_time - current_time
                await asyncio.sleep(sleep_time)
                current_time = time.perf_counter()
                next_frame_time = self._next_frame_time
                if next_frame_time is None:
                    break

            frame_to_write = None
            is_duplicate = False
            write_time_unix = time.time()

            if self._latest_frame is not None:
                frame_to_write = self._latest_frame
                metadata = self._latest_frame_metadata
                last_frame_used = frame_to_write
            elif last_frame_used is not None:
                frame_to_write = last_frame_used
                metadata = FrameTimingMetadata(
                    capture_monotonic=None,  # This is a duplicate, no new capture time
                    capture_unix=None,       # This is a duplicate, no new capture time
                    requested_fps=self.config.fps,
                    is_duplicate=True,
                    camera_frame_index=getattr(self._latest_frame_metadata, 'camera_frame_index', None) if self._latest_frame_metadata else None,
                )
                is_duplicate = True
                self._duplicated_frames += 1
            else:
                self._skipped_frames += 1
                self._next_frame_time += frame_interval
                continue

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

            next_frame_time = self._next_frame_time
            if next_frame_time is None:
                break
            self._next_frame_time = next_frame_time + frame_interval

            # Clear the latest frame after using it (to detect new vs duplicate)
            if not is_duplicate:
                self._latest_frame = None

    async def _frame_camera_loop(self) -> None:
        """
        Camera-based frame selection (Phase 3.1).

        Only writes unique camera frames (no duplicates).
        Variable timing in output, but frame-accurate analysis.
        """
        if self.config.fps <= 0:
            return

        last_camera_index = -1
        frame_interval = 1.0 / self.config.fps

        while True:
            if not self._is_recording:
                break

            frame_queue = self._frame_queue
            if frame_queue is None:
                break

            if self._latest_frame is None:
                await asyncio.sleep(0.01)
                continue

            metadata = self._latest_frame_metadata
            if metadata is None:
                await asyncio.sleep(0.01)
                continue

            # Only process new camera frames
            camera_frame_index = metadata.camera_frame_index
            if camera_frame_index is None or camera_frame_index == last_camera_index:
                await asyncio.sleep(0.001)
                continue

            last_camera_index = camera_frame_index

            # Apply frame rate limiting
            camera_fps = metadata.available_camera_fps or 30.0
            recording_fps = self.config.fps
            frame_ratio = max(1, int(camera_fps / recording_fps))

            if camera_frame_index % frame_ratio != 0:
                self._skipped_frames += 1
                continue

            current_time = time.perf_counter()
            queued = _QueuedFrame(
                frame=self._latest_frame,
                enqueued_monotonic=current_time,
                metadata=metadata,
            )

            try:
                frame_queue.put_nowait(queued)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    _ = frame_queue.get_nowait()
                frame_queue.put_nowait(queued)

            # Clear latest frame
            self._latest_frame = None

    def _ensure_module_subdir(self, base_dir: Path) -> Path:
        return ensure_module_data_dir(base_dir, self.MODULE_SUBDIR_NAME)

    async def _log_frame_timing(
        self,
        queued: _QueuedFrame,
        write_time_unix: float,
        write_start_monotonic: float,
        write_end_monotonic: float,
        backlog_after: int,
    ) -> None:
        if self._frame_timing_file is None:
            return

        queue_delay = write_start_monotonic - queued.enqueued_monotonic

        capture_latency: Optional[float] = None
        if queued.metadata.capture_monotonic is not None:
            capture_latency = write_start_monotonic - queued.metadata.capture_monotonic

        write_duration = write_end_monotonic - write_start_monotonic

        self._written_frames += 1
        self._recorded_frame_count += 1
        self._last_write_monotonic = write_start_monotonic

        def fmt(value: Optional[float]) -> str:
            return f"{value:.6f}" if value is not None else ""

        row = (
            f"{self._written_frames},{write_time_unix:.6f},{fmt(queue_delay)},{fmt(capture_latency)},{fmt(write_duration)},{backlog_after},"
            f"{queued.metadata.camera_frame_index if queued.metadata.camera_frame_index is not None else ''},"
            f"{queued.metadata.display_frame_index if queued.metadata.display_frame_index is not None else ''},"
            f"{fmt(queued.metadata.capture_unix)},{fmt(queued.metadata.gaze_timestamp)},"
            f"{fmt(queued.metadata.available_camera_fps)},{queued.metadata.dropped_frames_total if queued.metadata.dropped_frames_total is not None else ''},"
            f"{queued.metadata.duplicates_total if queued.metadata.duplicates_total is not None else ''},"
            f"{1 if queued.metadata.is_duplicate else 0}\n"
        )

        # Offload blocking file I/O to thread pool
        await asyncio.to_thread(self._frame_timing_file.write, row)
        # Batch flushes: flush every 30 frames (~6 seconds at 5fps) to reduce I/O
        self._timing_rows_since_flush += 1
        if self._timing_rows_since_flush >= 30:
            await asyncio.to_thread(self._frame_timing_file.flush)
            self._timing_rows_since_flush = 0
