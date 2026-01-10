from pathlib import Path
import asyncio
import logging
import time
from typing import Optional, Callable, Awaitable, Union

from ..capture.frame import CapturedFrame, AudioChunk
from .encoder import VideoEncoder
from .muxer import TimestampedMuxer, LegacyAVMuxer, HAS_AV
from .timing_writer import TimingCSVWriter

logger = logging.getLogger(__name__)


class RecordingSession:
    def __init__(
        self,
        session_dir: Path,
        device_id: str,
        trial_number: int,
        resolution: tuple[int, int],
        fps: int,
        with_audio: bool = False,
        audio_sample_rate: int = 48000,
        audio_channels: int = 2,
    ):
        self._session_dir = session_dir
        self._device_id = device_id
        self._trial_number = trial_number
        self._resolution = resolution
        self._fps = fps
        self._with_audio = with_audio
        self._audio_sample_rate = audio_sample_rate
        self._audio_channels = audio_channels

        safe_device_id = device_id.replace(":", "_").replace("-", "_")
        self._output_dir = session_dir / safe_device_id
        self._output_dir.mkdir(parents=True, exist_ok=True)

        ext = "mp4" if with_audio else "avi"
        self._video_path = self._output_dir / f"trial_{trial_number:03d}.{ext}"
        self._timing_path = self._output_dir / f"trial_{trial_number:03d}_timing.csv"

        self._encoder: Optional[VideoEncoder] = None
        self._muxer: Optional[Union[TimestampedMuxer, LegacyAVMuxer]] = None
        self._timing_writer: Optional[TimingCSVWriter] = None

        self._running = False
        self._audio_pts = 0

    async def start(self) -> None:
        self._timing_writer = TimingCSVWriter(
            self._timing_path,
            self._trial_number,
            self._device_id,
        )
        await self._timing_writer.start()

        if self._with_audio:
            sync_ns = time.monotonic_ns()

            if HAS_AV:
                self._muxer = TimestampedMuxer(
                    self._video_path,
                    self._fps,
                    self._resolution,
                    self._audio_sample_rate,
                    self._audio_channels,
                    sync_ns=sync_ns,
                )
            else:
                logger.warning("PyAV not available, audio sync may be imprecise")
                self._muxer = LegacyAVMuxer(
                    self._video_path,
                    self._fps,
                    self._resolution,
                    self._audio_sample_rate,
                    self._audio_channels,
                )
            await self._muxer.start()
        else:
            self._encoder = VideoEncoder(
                self._video_path,
                self._resolution,
                self._fps,
            )
            await self._encoder.start()

        self._running = True

    async def write_frame(self, frame: CapturedFrame) -> None:
        if not self._running:
            return

        if self._muxer:
            await self._muxer.write_video_frame(frame)
        elif self._encoder:
            await self._encoder.write_frame(frame)

        if self._timing_writer:
            await self._timing_writer.write_frame(frame, self._audio_pts)

    async def write_audio(self, chunk: AudioChunk) -> None:
        if not self._running or not self._muxer:
            return

        await self._muxer.write_audio_chunk(chunk)
        self._audio_pts = chunk.chunk_number

    async def stop(self) -> None:
        self._running = False

        if self._muxer:
            await self._muxer.stop()
            self._muxer = None

        if self._encoder:
            await self._encoder.stop()
            self._encoder = None

        if self._timing_writer:
            await self._timing_writer.stop()
            self._timing_writer = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def video_path(self) -> Path:
        return self._video_path

    @property
    def timing_path(self) -> Path:
        return self._timing_path

    @property
    def frame_count(self) -> int:
        if self._muxer:
            return self._muxer.frame_count
        if self._encoder:
            return self._encoder.frame_count
        return 0

    @property
    def with_audio(self) -> bool:
        return self._with_audio
