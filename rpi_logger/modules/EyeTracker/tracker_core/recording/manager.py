"""EyeTracker Recording Manager - Clean 6-file output matching hardware streams.

Output files per recording:
- WORLD_*.mp4: Scene camera video with gaze overlay
- EYES_*.mp4: Eye camera video (384x192)
- AUDIO.wav: Microphone audio
- GAZE.csv: Gaze stream data (30 columns)
- IMU.csv: IMU stream data (13 columns)
- EVENTS.csv: Eye events (blinks, fixations, saccades)
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import datetime
import io
import time
import wave
from pathlib import Path
from typing import Optional, Any, TYPE_CHECKING

import numpy as np

from rpi_logger.modules.base.recording import RecordingManagerBase
from rpi_logger.modules.base.storage_utils import (
    ensure_module_data_dir,
    module_filename_prefix,
)
from rpi_logger.core.logging_utils import get_module_logger
from ..config.tracker_config import TrackerConfig as Config
from ..rolling_fps import RollingFPS
from .async_csv_writer import AsyncCSVWriter
from .video_encoder import VideoEncoder

if TYPE_CHECKING:
    from pupil_labs.realtime_api.streaming import AudioFrame

logger = get_module_logger(__name__)

# CSV Headers
GAZE_HEADER = (
    "timestamp,timestamp_ns,stream_type,worn,x,y,"
    "left_x,left_y,right_x,right_y,"
    "pupil_diameter_left,pupil_diameter_right,"
    "eyeball_center_left_x,eyeball_center_left_y,eyeball_center_left_z,"
    "optical_axis_left_x,optical_axis_left_y,optical_axis_left_z,"
    "eyeball_center_right_x,eyeball_center_right_y,eyeball_center_right_z,"
    "optical_axis_right_x,optical_axis_right_y,optical_axis_right_z,"
    "eyelid_angle_top_left,eyelid_angle_bottom_left,eyelid_aperture_left,"
    "eyelid_angle_top_right,eyelid_angle_bottom_right,eyelid_aperture_right"
)

IMU_HEADER = (
    "timestamp,timestamp_ns,gyro_x,gyro_y,gyro_z,accel_x,accel_y,accel_z,"
    "quat_w,quat_x,quat_y,quat_z,temperature"
)

EVENTS_HEADER = (
    "timestamp,timestamp_ns,event_type,event_subtype,confidence,duration,"
    "start_time_ns,end_time_ns,start_gaze_x,start_gaze_y,end_gaze_x,end_gaze_y,"
    "mean_gaze_x,mean_gaze_y,amplitude_pixels,amplitude_angle_deg,"
    "mean_velocity,max_velocity"
)


class RecordingManager(RecordingManagerBase):
    """Records 6 output files matching hardware streams."""

    MODULE_SUBDIR_NAME = "EyeTracker-Neon"

    def __init__(self, config: Config, *, use_ffmpeg: bool = True, **kwargs):
        super().__init__(device_id="eye_tracker")
        self.config = config
        self.use_ffmpeg = use_ffmpeg

        # Output filenames (6 files)
        self.world_video_filename: Optional[str] = None
        self.eyes_video_filename: Optional[str] = None
        self.audio_filename: Optional[str] = None
        self.gaze_filename: Optional[str] = None
        self.imu_filename: Optional[str] = None
        self.events_filename: Optional[str] = None

        # Video encoders
        self._world_video_encoder = VideoEncoder(
            config.resolution, config.fps, use_ffmpeg=use_ffmpeg
        )
        self._eyes_video_encoder: Optional[VideoEncoder] = None

        # CSV writers
        self._gaze_writer: Optional[AsyncCSVWriter] = None
        self._imu_writer: Optional[AsyncCSVWriter] = None
        self._event_writer: Optional[AsyncCSVWriter] = None

        # Audio state
        self._audio_frame_queue: Optional[asyncio.Queue[Any]] = None
        self._audio_writer_task: Optional[asyncio.Task] = None
        self._audio_queue_sentinel: object = object()

        # Eyes video state
        self._eyes_frame_queue: Optional[asyncio.Queue[Any]] = None
        self._eyes_writer_task: Optional[asyncio.Task] = None
        self._eyes_queue_sentinel: object = object()

        # World video state
        self._world_frame_queue: Optional[asyncio.Queue[Any]] = None
        self._world_writer_task: Optional[asyncio.Task] = None
        self._world_queue_sentinel: object = object()

        # Counters
        self._world_frames_written = 0
        self._eyes_frames_written = 0
        self._gaze_samples_written = 0
        self._imu_samples_written = 0
        self._event_samples_written = 0
        self._last_gaze_timestamp: Optional[float] = None

        # FPS tracking for recording output
        self._record_fps_tracker = RollingFPS(window_seconds=5.0)

        # Output directory
        self._output_root = Path(config.output_dir)
        self._output_root.mkdir(parents=True, exist_ok=True)

        # Experiment state
        self._current_experiment_dir: Optional[Path] = None
        self._current_experiment_label: Optional[str] = None
        self._current_experiment_started_at: Optional[datetime.datetime] = None
        self._recordings_this_experiment = 0
        self._trial_label: Optional[str] = None

    def set_session_context(
        self, session_dir: Path, trial_number: int = 1, *, trial_label: Optional[str] = None
    ) -> None:
        """Set session context for future recordings."""
        super().set_session_context(session_dir, trial_number)
        self._trial_label = trial_label

    def start_experiment(self, label: Optional[str] = None) -> Path:
        """Start a new experiment session (creates experiment directory)."""
        if self._is_recording:
            raise RuntimeError("Stop the active recording before starting a new experiment")

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = None
        if label:
            candidate = "".join(
                ch if ch.isalnum() or ch in {"-", "_"} else "-"
                for ch in label.strip()
            )
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

        return experiment_dir

    @property
    def current_experiment_dir(self) -> Optional[Path]:
        """Get the current experiment directory."""
        return self._current_experiment_dir

    async def start_recording(
        self, session_dir: Optional[Path] = None, trial_number: int = 1
    ) -> Path:
        """Start recording to 6 output files."""
        if self._is_recording:
            if self.world_video_filename:
                return Path(self.world_video_filename)
            raise RuntimeError("Already recording but no filename set")

        # Determine output directory
        if session_dir is not None:
            target_dir = self._ensure_module_subdir(session_dir)
        elif self._current_experiment_dir is not None:
            target_dir = self._ensure_module_subdir(self._current_experiment_dir)
        elif self._current_session_dir is not None:
            target_dir = self._current_session_dir
        else:
            target_dir = self._ensure_module_subdir(self._output_root)

        target_dir.mkdir(parents=True, exist_ok=True)
        self._current_session_dir = target_dir
        self._current_trial_number = trial_number

        # Generate filenames
        w, h = self.config.resolution
        prefix = module_filename_prefix(
            target_dir, self.MODULE_SUBDIR_NAME, trial_number, code="ET"
        )

        self.world_video_filename = str(
            target_dir / f"{prefix}_WORLD_{w}x{h}_{self.config.fps}fps.mp4"
        )
        self.eyes_video_filename = str(
            target_dir / f"{prefix}_EYES_384x192_{self.config.eyes_fps}fps.mp4"
        )
        self.audio_filename = str(target_dir / f"{prefix}_AUDIO.wav")
        self.gaze_filename = str(target_dir / f"{prefix}_GAZE.csv")
        self.imu_filename = str(target_dir / f"{prefix}_IMU.csv")
        self.events_filename = str(target_dir / f"{prefix}_EVENTS.csv")

        try:
            # Start world video encoder
            await self._world_video_encoder.start(Path(self.world_video_filename))
            self._world_frame_queue = asyncio.Queue(maxsize=max(int(self.config.fps * 2), 30))
            self._world_writer_task = asyncio.create_task(self._world_writer_loop())

            # Start eyes video encoder
            self._eyes_video_encoder = VideoEncoder(
                (384, 192), fps=self.config.eyes_fps, use_ffmpeg=self.use_ffmpeg
            )
            await self._eyes_video_encoder.start(Path(self.eyes_video_filename))
            self._eyes_frame_queue = asyncio.Queue(maxsize=120)
            self._eyes_writer_task = asyncio.create_task(self._eyes_writer_loop())

            # Start CSV writers
            self._gaze_writer = AsyncCSVWriter(
                header=GAZE_HEADER, flush_threshold=32, queue_size=512
            )
            await self._gaze_writer.start(Path(self.gaze_filename))

            self._imu_writer = AsyncCSVWriter(
                header=IMU_HEADER, flush_threshold=128, queue_size=1024
            )
            await self._imu_writer.start(Path(self.imu_filename))

            self._event_writer = AsyncCSVWriter(
                header=EVENTS_HEADER, flush_threshold=64, queue_size=512
            )
            await self._event_writer.start(Path(self.events_filename))

            # Start audio writer
            self._audio_frame_queue = asyncio.Queue(
                maxsize=max(int(self.config.fps * 6), 240)
            )
            self._audio_writer_task = asyncio.create_task(self._audio_writer_loop())

            # Reset counters
            self._world_frames_written = 0
            self._eyes_frames_written = 0
            self._gaze_samples_written = 0
            self._imu_samples_written = 0
            self._event_samples_written = 0
            self._last_gaze_timestamp = None
            self._record_fps_tracker.reset()
            self._is_recording = True

            return Path(self.world_video_filename)

        except Exception as exc:
            logger.error("Failed to start recording: %s", exc)
            await self._cleanup_on_failure()
            raise

    async def stop_recording(self) -> dict:
        """Stop recording and close all 6 files."""
        if not self._is_recording:
            return {
                "duration_seconds": 0.0,
                "world_frames": 0,
                "eyes_frames": 0,
                "output_files": [],
            }

        self._is_recording = False
        output_files = []

        # Stop world video
        if self._world_frame_queue is not None:
            with contextlib.suppress(Exception):
                self._world_frame_queue.put_nowait(self._world_queue_sentinel)
        if self._world_writer_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._world_writer_task
        self._world_writer_task = None
        self._world_frame_queue = None

        await self._world_video_encoder.stop()
        if self.world_video_filename:
            output_files.append(Path(self.world_video_filename))

        # Stop eyes video
        if self._eyes_frame_queue is not None:
            with contextlib.suppress(Exception):
                self._eyes_frame_queue.put_nowait(self._eyes_queue_sentinel)
        if self._eyes_writer_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._eyes_writer_task
        self._eyes_writer_task = None
        self._eyes_frame_queue = None

        if self._eyes_video_encoder is not None:
            await self._eyes_video_encoder.stop()
            if self.eyes_video_filename and Path(self.eyes_video_filename).exists():
                output_files.append(Path(self.eyes_video_filename))
            self._eyes_video_encoder = None

        # Stop audio
        if self._audio_frame_queue is not None:
            with contextlib.suppress(Exception):
                self._audio_frame_queue.put_nowait(self._audio_queue_sentinel)
        if self._audio_writer_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._audio_writer_task
        self._audio_writer_task = None
        self._audio_frame_queue = None
        if self.audio_filename and Path(self.audio_filename).exists():
            output_files.append(Path(self.audio_filename))

        # Stop CSV writers
        if self._gaze_writer:
            await self._gaze_writer.stop()
            if self.gaze_filename:
                output_files.append(Path(self.gaze_filename))
            self._gaze_writer = None

        if self._imu_writer:
            await self._imu_writer.stop()
            if self.imu_filename:
                output_files.append(Path(self.imu_filename))
            self._imu_writer = None

        if self._event_writer:
            await self._event_writer.stop()
            if self.events_filename:
                output_files.append(Path(self.events_filename))
            self._event_writer = None

        return {
            "world_frames": self._world_frames_written,
            "eyes_frames": self._eyes_frames_written,
            "gaze_samples": self._gaze_samples_written,
            "imu_samples": self._imu_samples_written,
            "event_samples": self._event_samples_written,
            "output_files": [str(f) for f in output_files],
        }

    def write_frame(self, frame: np.ndarray, metadata: Any = None) -> None:
        """Queue a world video frame for recording.

        Args:
            frame: Video frame to record
            metadata: Ignored (kept for base class compatibility)
        """
        if not self._is_recording or self._world_frame_queue is None:
            return

        try:
            self._world_frame_queue.put_nowait(frame)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._world_frame_queue.get_nowait()
            self._world_frame_queue.put_nowait(frame)

    def write_eyes_frame(
        self,
        frame: Optional[np.ndarray],
        timestamp_unix: Optional[float] = None,
        timestamp_ns: Optional[int] = None,
    ) -> None:
        """Queue an eyes frame for recording."""
        if not self._is_recording or self._eyes_frame_queue is None or frame is None:
            return

        try:
            self._eyes_frame_queue.put_nowait(frame)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._eyes_frame_queue.get_nowait()
            self._eyes_frame_queue.put_nowait(frame)

    def write_audio_sample(self, audio: Optional["AudioFrame"]) -> None:
        """Queue an audio frame for recording."""
        if not self._is_recording or self._audio_frame_queue is None or audio is None:
            return

        try:
            self._audio_frame_queue.put_nowait(audio)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._audio_frame_queue.get_nowait()
            self._audio_frame_queue.put_nowait(audio)

    def write_gaze_sample(self, gaze: Optional[Any]) -> None:
        """Write a gaze sample to CSV (30 columns)."""
        if not self._is_recording or self._gaze_writer is None or gaze is None:
            return

        timestamp = getattr(gaze, "timestamp_unix_seconds", None)
        if timestamp is not None and timestamp == self._last_gaze_timestamp:
            return  # Skip duplicate

        try:
            line = self._compose_gaze_line(gaze)
            self._gaze_writer.enqueue(line)
            self._last_gaze_timestamp = timestamp
            self._gaze_samples_written += 1
        except Exception as exc:
            logger.error("Failed to write gaze sample: %s", exc)

    def write_imu_sample(self, imu: Optional[Any]) -> None:
        """Write an IMU sample to CSV."""
        if not self._is_recording or self._imu_writer is None or imu is None:
            return

        try:
            timestamp = getattr(imu, "timestamp_unix_seconds", None)
            timestamp_ns = getattr(imu, "timestamp_unix_ns", None)

            gyro = self._extract_xyz(getattr(imu, "gyro_data", None))
            accel = self._extract_xyz(getattr(imu, "accel_data", None))
            quat = self._extract_quat(getattr(imu, "quaternion", None))
            temperature = getattr(imu, "temperature", None)

            fields = [
                self._fmt(timestamp),
                self._fmt(timestamp_ns),
                *gyro,
                *accel,
                *quat,
                self._fmt(temperature),
            ]
            self._imu_writer.enqueue(self._csv_line(fields))
            self._imu_samples_written += 1
        except Exception as exc:
            logger.error("Failed to write IMU sample: %s", exc)

    def write_event_sample(self, event: Optional[Any]) -> None:
        """Write an eye event to CSV."""
        if not self._is_recording or self._event_writer is None or event is None:
            return

        try:
            timestamp = getattr(event, "timestamp_unix_seconds", None)
            timestamp_ns = getattr(event, "timestamp_unix_ns", None)
            event_type = getattr(event, "type", None) or getattr(event, "event_type", None)
            subtype = getattr(event, "category", None) or getattr(event, "event_subtype", None)
            confidence = getattr(event, "confidence", None)

            # Calculate duration if not directly available
            duration = getattr(event, "duration", None)
            start_ns = getattr(event, "start_time_ns", None)
            end_ns = getattr(event, "end_time_ns", None)
            if duration is None and start_ns is not None and end_ns is not None:
                duration = (end_ns - start_ns) / 1e9

            fields = [
                self._fmt(timestamp),
                self._fmt(timestamp_ns),
                self._fmt(event_type),
                self._fmt(subtype),
                self._fmt(confidence),
                self._fmt(duration),
                self._fmt(start_ns),
                self._fmt(end_ns),
                self._fmt(getattr(event, "start_gaze_x", None)),
                self._fmt(getattr(event, "start_gaze_y", None)),
                self._fmt(getattr(event, "end_gaze_x", None)),
                self._fmt(getattr(event, "end_gaze_y", None)),
                self._fmt(getattr(event, "mean_gaze_x", None)),
                self._fmt(getattr(event, "mean_gaze_y", None)),
                self._fmt(getattr(event, "amplitude_pixels", None)),
                self._fmt(getattr(event, "amplitude_angle_deg", None)),
                self._fmt(getattr(event, "mean_velocity", None)),
                self._fmt(getattr(event, "max_velocity", None)),
            ]
            self._event_writer.enqueue(self._csv_line(fields))
            self._event_samples_written += 1
        except Exception as exc:
            logger.error("Failed to write event sample: %s", exc)

    async def cleanup(self) -> None:
        """Clean up resources."""
        await self.stop_recording()

    async def pause_recording(self) -> None:
        """Pause recording (not supported)."""
        raise NotImplementedError("Pause not supported by EyeTracker recording")

    async def resume_recording(self) -> None:
        """Resume recording (not supported)."""
        raise NotImplementedError("Resume not supported by EyeTracker recording")

    async def toggle_recording(self) -> None:
        """Toggle recording state."""
        if self._is_recording:
            await self.stop_recording()
        else:
            await self.start_recording()

    def get_stats(self) -> dict:
        """Get current recording statistics."""
        return {
            "is_recording": self._is_recording,
            "world_frames_written": self._world_frames_written,
            "eyes_frames_written": self._eyes_frames_written,
            "gaze_samples_written": self._gaze_samples_written,
            "imu_samples_written": self._imu_samples_written,
            "event_samples_written": self._event_samples_written,
            "world_video_filename": self.world_video_filename,
            "eyes_video_filename": self.eyes_video_filename,
            "audio_filename": self.audio_filename,
            "gaze_filename": self.gaze_filename,
            "imu_filename": self.imu_filename,
            "events_filename": self.events_filename,
        }

    # Properties for compatibility with existing code
    @property
    def recording_filename(self) -> Optional[str]:
        """Alias for world_video_filename."""
        return self.world_video_filename

    @property
    def recorded_frame_count(self) -> int:
        """Number of world video frames written."""
        return self._world_frames_written

    @property
    def duplicated_frames(self) -> int:
        """Not tracked in simplified implementation."""
        return 0

    @property
    def current_experiment_label(self) -> Optional[str]:
        """Return experiment label."""
        return self._current_experiment_label

    def get_record_fps(self) -> float:
        """Get current recording output FPS."""
        if not self._is_recording:
            return 0.0
        return self._record_fps_tracker.get_fps()

    # === Private Methods ===

    async def _world_writer_loop(self) -> None:
        """Background task to write world video frames.

        Frames are pre-filtered by GazeTracker._process_frames() before being
        queued, so no skip logic is needed here - all frames received should
        be written.
        """
        if self._world_frame_queue is None:
            return

        while True:
            frame = await self._world_frame_queue.get()
            if frame is self._world_queue_sentinel:
                break

            await self._world_video_encoder.write_frame(frame)
            self._world_frames_written += 1
            self._record_fps_tracker.add_frame()

    async def _eyes_writer_loop(self) -> None:
        """Background task to write eyes video frames.

        Frames are pre-filtered by GazeTracker._process_frames() before being
        queued, so no skip logic is needed here - all frames received should
        be written. This matches the world_writer_loop pattern.
        """
        if self._eyes_frame_queue is None or self._eyes_video_encoder is None:
            return

        while True:
            frame = await self._eyes_frame_queue.get()
            if frame is self._eyes_queue_sentinel:
                break

            await self._eyes_video_encoder.write_frame(frame)
            self._eyes_frames_written += 1

    async def _audio_writer_loop(self) -> None:
        """Background task to write audio to WAV file."""
        if self._audio_frame_queue is None or not self.audio_filename:
            return

        wave_file: Optional[wave.Wave_write] = None

        try:
            while True:
                item = await self._audio_frame_queue.get()
                if item is self._audio_queue_sentinel:
                    break

                sample_rate, channels, chunks = self._prepare_audio_frame(item)
                if not chunks or sample_rate is None or channels is None:
                    continue

                if wave_file is None:
                    wave_file = wave.open(self.audio_filename, "wb")
                    wave_file.setnchannels(channels)
                    wave_file.setsampwidth(2)  # 16-bit
                    wave_file.setframerate(sample_rate)

                for chunk in chunks:
                    wave_file.writeframes(chunk)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Audio writer loop failed: %s", exc)
        finally:
            if wave_file is not None:
                wave_file.close()

    def _prepare_audio_frame(
        self, audio_frame: "AudioFrame"
    ) -> tuple[Optional[int], Optional[int], list[bytes]]:
        """Extract audio data from frame."""
        try:
            av_frame = audio_frame.av_frame
            sample_rate = getattr(av_frame, "sample_rate", None)
            layout = getattr(av_frame, "layout", None)
            channels = None
            if layout is not None:
                channels = getattr(layout, "nb_channels", None)
                if channels is None:
                    channel_list = getattr(layout, "channels", None)
                    if channel_list is not None:
                        channels = len(channel_list)

            # Use av_frame.to_ndarray() directly instead of to_resampled_ndarray()
            # The resampler method returns an empty iterator; direct access works
            samples = av_frame.to_ndarray()

            if samples is None or samples.size == 0:
                return None, None, []

            # Infer channels from array shape if not detected from layout
            if channels is None:
                channels = samples.shape[0] if samples.ndim == 2 else 1

            # Convert to int16 for WAV (handle various input formats)
            if samples.dtype in (np.float32, np.float64):
                # Float audio is typically in range [-1.0, 1.0]
                samples = np.clip(samples, -1.0, 1.0)
                samples = (samples * 32767).astype(np.int16)
            elif samples.dtype != np.int16:
                samples = samples.astype(np.int16)

            # Ensure shape is (channels, samples) then transpose for interleaved WAV
            if samples.ndim == 1:
                samples = samples.reshape(1, -1)

            chunk = np.ascontiguousarray(samples.T).tobytes()
            return sample_rate, channels, [chunk]
        except Exception as exc:
            logger.error("Failed to prepare audio frame: %s", exc)
            return None, None, []

    def _compose_gaze_line(self, gaze: Any) -> str:
        """Compose a 30-column gaze CSV line."""
        timestamp = getattr(gaze, "timestamp_unix_seconds", None)
        timestamp_ns = getattr(gaze, "timestamp_unix_ns", None)
        stream_type = type(gaze).__name__
        worn = getattr(gaze, "worn", None)
        worn_int = int(bool(worn)) if worn is not None else ""

        x = getattr(gaze, "x", None)
        y = getattr(gaze, "y", None)

        # Per-eye coordinates
        left_x = left_y = right_x = right_y = None
        left_point = getattr(gaze, "left", None)
        if left_point:
            left_x = getattr(left_point, "x", None)
            left_y = getattr(left_point, "y", None)
        right_point = getattr(gaze, "right", None)
        if right_point:
            right_x = getattr(right_point, "x", None)
            right_y = getattr(right_point, "y", None)

        fields = [
            self._fmt(timestamp),
            self._fmt(timestamp_ns),
            self._fmt(stream_type),
            self._fmt(worn_int),
            self._fmt(x),
            self._fmt(y),
            self._fmt(left_x),
            self._fmt(left_y),
            self._fmt(right_x),
            self._fmt(right_y),
            self._fmt(getattr(gaze, "pupil_diameter_left", None)),
            self._fmt(getattr(gaze, "pupil_diameter_right", None)),
            self._fmt(getattr(gaze, "eyeball_center_left_x", None)),
            self._fmt(getattr(gaze, "eyeball_center_left_y", None)),
            self._fmt(getattr(gaze, "eyeball_center_left_z", None)),
            self._fmt(getattr(gaze, "optical_axis_left_x", None)),
            self._fmt(getattr(gaze, "optical_axis_left_y", None)),
            self._fmt(getattr(gaze, "optical_axis_left_z", None)),
            self._fmt(getattr(gaze, "eyeball_center_right_x", None)),
            self._fmt(getattr(gaze, "eyeball_center_right_y", None)),
            self._fmt(getattr(gaze, "eyeball_center_right_z", None)),
            self._fmt(getattr(gaze, "optical_axis_right_x", None)),
            self._fmt(getattr(gaze, "optical_axis_right_y", None)),
            self._fmt(getattr(gaze, "optical_axis_right_z", None)),
            self._fmt(getattr(gaze, "eyelid_angle_top_left", None)),
            self._fmt(getattr(gaze, "eyelid_angle_bottom_left", None)),
            self._fmt(getattr(gaze, "eyelid_aperture_left", None)),
            self._fmt(getattr(gaze, "eyelid_angle_top_right", None)),
            self._fmt(getattr(gaze, "eyelid_angle_bottom_right", None)),
            self._fmt(getattr(gaze, "eyelid_aperture_right", None)),
        ]
        return self._csv_line(fields)

    def _extract_xyz(self, source: Any) -> list[str]:
        """Extract x, y, z components from a source object."""
        if source is None:
            return ["", "", ""]
        x = getattr(source, "x", None) if hasattr(source, "x") else source.get("x") if isinstance(source, dict) else None
        y = getattr(source, "y", None) if hasattr(source, "y") else source.get("y") if isinstance(source, dict) else None
        z = getattr(source, "z", None) if hasattr(source, "z") else source.get("z") if isinstance(source, dict) else None
        return [self._fmt(x), self._fmt(y), self._fmt(z)]

    def _extract_quat(self, source: Any) -> list[str]:
        """Extract w, x, y, z quaternion components."""
        if source is None:
            return ["", "", "", ""]
        w = getattr(source, "w", None) if hasattr(source, "w") else source.get("w") if isinstance(source, dict) else None
        x = getattr(source, "x", None) if hasattr(source, "x") else source.get("x") if isinstance(source, dict) else None
        y = getattr(source, "y", None) if hasattr(source, "y") else source.get("y") if isinstance(source, dict) else None
        z = getattr(source, "z", None) if hasattr(source, "z") else source.get("z") if isinstance(source, dict) else None
        return [self._fmt(w), self._fmt(x), self._fmt(y), self._fmt(z)]

    @staticmethod
    def _fmt(value: Any) -> str:
        """Format a value for CSV output."""
        if value is None:
            return ""
        if isinstance(value, float):
            text = f"{value:.9f}"
            return text.rstrip("0").rstrip(".") if "." in text else text
        return str(value)

    def _csv_line(self, fields: list[str]) -> str:
        """Compose a CSV line from fields."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="")
        writer.writerow(fields)
        return buffer.getvalue() + "\n"

    def _ensure_module_subdir(self, base_dir: Path) -> Path:
        """Ensure module subdirectory exists."""
        return ensure_module_data_dir(base_dir, self.MODULE_SUBDIR_NAME)

    async def _cleanup_on_failure(self) -> None:
        """Clean up resources after a failed start."""
        await self._world_video_encoder.cleanup()

        if self._eyes_video_encoder:
            await self._eyes_video_encoder.cleanup()
            self._eyes_video_encoder = None

        if self._gaze_writer:
            await self._gaze_writer.cleanup()
            self._gaze_writer = None

        if self._imu_writer:
            await self._imu_writer.cleanup()
            self._imu_writer = None

        if self._event_writer:
            await self._event_writer.cleanup()
            self._event_writer = None

        for task in [self._world_writer_task, self._eyes_writer_task, self._audio_writer_task]:
            if task:
                task.cancel()

        self._world_writer_task = None
        self._eyes_writer_task = None
        self._audio_writer_task = None
        self._world_frame_queue = None
        self._eyes_frame_queue = None
        self._audio_frame_queue = None
