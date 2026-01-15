"""Audio/Video muxer using PyAV."""

import asyncio
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..capture import CapturedFrame, AudioChunk

logger = logging.getLogger(__name__)


class AVMuxer:
    """Muxes video and audio streams using PyAV.

    Creates MP4 files with H.264 video and AAC audio.
    Cross-platform compatible (Windows/Mac/Linux/Pi).
    """

    def __init__(
        self,
        path: Path,
        resolution: tuple[int, int],
        video_fps: int,
        sample_rate: int,
        audio_channels: int,
    ):
        """Initialize muxer.

        Args:
            path: Output file path (.mp4)
            resolution: Video resolution (width, height)
            video_fps: Video frame rate
            sample_rate: Audio sample rate (Hz)
            audio_channels: Number of audio channels
        """
        self._path = path
        self._resolution = resolution
        self._video_fps = video_fps
        self._sample_rate = sample_rate
        self._audio_channels = audio_channels

        self._container = None
        self._video_stream = None
        self._audio_stream = None

        self._video_frame_count = 0
        self._audio_sample_count = 0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Open output file and initialize streams."""
        try:
            import av
        except ImportError:
            raise RuntimeError("PyAV not installed. Install with: pip install av")

        self._container = av.open(str(self._path), mode="w")

        from fractions import Fraction

        # Video stream - H.264
        self._video_stream = self._container.add_stream("libx264", rate=self._video_fps)
        self._video_stream.width = self._resolution[0]
        self._video_stream.height = self._resolution[1]
        self._video_stream.pix_fmt = "yuv420p"
        # Use high-resolution time_base for precise timestamps (codec may change it)
        self._video_stream.codec_context.time_base = Fraction(1, self._video_fps)
        # Fast encoding preset for real-time
        self._video_stream.options = {"preset": "ultrafast", "tune": "zerolatency"}

        # Audio stream - AAC (rate must be int, not float)
        # Set layout to configure channels (channels property is read-only in newer PyAV)
        sample_rate_int = int(self._sample_rate)
        self._audio_stream = self._container.add_stream("aac", rate=sample_rate_int)
        self._audio_stream.layout = "mono" if self._audio_channels == 1 else "stereo"
        self._audio_stream.codec_context.time_base = Fraction(1, sample_rate_int)

        self._video_frame_count = 0
        self._audio_sample_count = 0

        logger.info(
            "AVMuxer started: %s (video=%dx%d@%dfps, audio=%dHz/%dch)",
            self._path,
            *self._resolution,
            self._video_fps,
            self._sample_rate,
            self._audio_channels,
        )

    async def write_video(self, frame: "CapturedFrame") -> None:
        """Write a video frame.

        Args:
            frame: Captured video frame (BGR format)
        """
        if not self._container or not self._video_stream:
            return

        async with self._lock:
            await asyncio.to_thread(self._write_video_sync, frame)

    def _write_video_sync(self, frame: "CapturedFrame") -> None:
        """Synchronous video write (runs in thread)."""
        import av
        import cv2

        # Convert BGR to RGB
        rgb = cv2.cvtColor(frame.data, cv2.COLOR_BGR2RGB)

        # Create PyAV frame with pts in codec time_base units
        av_frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
        av_frame.pts = self._video_frame_count
        av_frame.time_base = self._video_stream.codec_context.time_base

        # Encode and write
        for packet in self._video_stream.encode(av_frame):
            self._container.mux(packet)

        self._video_frame_count += 1

    async def write_audio(self, chunk: "AudioChunk") -> None:
        """Write an audio chunk.

        Args:
            chunk: Audio chunk (float32 samples)
        """
        if not self._container or not self._audio_stream:
            return

        async with self._lock:
            await asyncio.to_thread(self._write_audio_sync, chunk)

    def _write_audio_sync(self, chunk: "AudioChunk") -> None:
        """Synchronous audio write (runs in thread)."""
        import av
        import numpy as np

        # Audio data is float32, reshape for channels
        audio_data = chunk.data
        if audio_data.ndim == 1:
            audio_data = audio_data.reshape(-1, 1)

        # Transpose to (channels, samples) for PyAV and ensure C-contiguous
        audio_data = np.ascontiguousarray(audio_data.T)

        # Create PyAV frame with pts in codec time_base units
        av_frame = av.AudioFrame.from_ndarray(audio_data, format="fltp", layout=self._audio_stream.layout.name)
        av_frame.sample_rate = chunk.sample_rate
        av_frame.pts = self._audio_sample_count
        av_frame.time_base = self._audio_stream.codec_context.time_base

        # Encode and write
        for packet in self._audio_stream.encode(av_frame):
            self._container.mux(packet)

        self._audio_sample_count += chunk.samples

    async def stop(self) -> None:
        """Flush streams and close file."""
        if not self._container:
            return

        async with self._lock:
            await asyncio.to_thread(self._stop_sync)

    def _stop_sync(self) -> None:
        """Synchronous stop (runs in thread)."""
        # Flush video stream
        if self._video_stream:
            for packet in self._video_stream.encode():
                self._container.mux(packet)

        # Flush audio stream
        if self._audio_stream:
            for packet in self._audio_stream.encode():
                self._container.mux(packet)

        self._container.close()
        self._container = None
        self._video_stream = None
        self._audio_stream = None

        logger.info(
            "AVMuxer stopped: %s (%d video frames, %d audio samples)",
            self._path,
            self._video_frame_count,
            self._audio_sample_count,
        )

    @property
    def video_frame_count(self) -> int:
        """Number of video frames written."""
        return self._video_frame_count

    @property
    def audio_sample_count(self) -> int:
        """Number of audio samples written."""
        return self._audio_sample_count
