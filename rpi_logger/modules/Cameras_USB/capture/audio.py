"""Audio capture using sounddevice."""

import contextlib
import logging
import os
import time
from typing import Optional

import numpy as np

from .frame import AudioChunk
from .ring_buffer import AudioRingBuffer

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _suppress_stderr():
    """Suppress stderr to hide ALSA/PortAudio warnings."""
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    old_stderr_fd = os.dup(2)
    try:
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(old_stderr_fd, 2)
        os.close(old_stderr_fd)
        os.close(devnull_fd)


class AudioCapture:
    """Audio capture using sounddevice library.

    Captures audio at hardware speed with callback-based delivery.
    """

    def __init__(
        self,
        device_index: int,
        sample_rate: int,
        channels: int,
        buffer: AudioRingBuffer,
        chunk_size: int = 1024,
        supported_rates: tuple[int, ...] = (),
    ):
        """Initialize audio capture.

        Args:
            device_index: Sounddevice device index
            sample_rate: Preferred sample rate (Hz)
            channels: Number of audio channels
            buffer: Ring buffer for audio chunks
            chunk_size: Samples per chunk
            supported_rates: Known supported sample rates for fallback
        """
        self._device_index = device_index
        self._preferred_rate = sample_rate
        self._supported_rates = supported_rates
        self._sample_rate = sample_rate
        self._channels = channels
        self._chunk_size = chunk_size
        self._buffer = buffer

        self._stream = None
        self._running = False
        self._chunk_number = 0

    def open(self) -> bool:
        """Open audio stream. Returns True on success."""
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice library not available")
            return False

        rates_to_try = self._build_rate_priority()
        for rate in rates_to_try:
            if self._try_open_stream(rate):
                self._sample_rate = rate
                logger.info(
                    "AudioCapture opened: device=%d, rate=%d, channels=%d",
                    self._device_index,
                    self._sample_rate,
                    self._channels,
                )
                return True

        logger.error("No supported sample rate found (tried: %s)", rates_to_try)
        return False

    def _build_rate_priority(self) -> list[int]:
        """Build priority-ordered list of sample rates to try."""
        rates = [self._preferred_rate]
        for r in self._supported_rates:
            if r not in rates:
                rates.append(r)
        for r in (48000, 44100, 32000, 16000):
            if r not in rates:
                rates.append(r)
        return rates

    def _try_open_stream(self, rate: int) -> bool:
        """Try to open audio stream at given sample rate."""
        try:
            import sounddevice as sd

            with _suppress_stderr():
                self._stream = sd.InputStream(
                    device=self._device_index,
                    samplerate=rate,
                    channels=self._channels,
                    blocksize=self._chunk_size,
                    dtype=np.float32,
                    callback=self._audio_callback,
                )
            return True
        except Exception as e:
            logger.debug("Failed to open audio at %d Hz: %s", rate, e)
            return False

    def start(self) -> None:
        """Start audio capture."""
        if self._running:
            return
        if not self._stream:
            if not self.open():
                return

        self._running = True
        try:
            self._stream.start()
            logger.info("Audio capture started")
        except Exception as e:
            self._running = False
            logger.error("Failed to start audio: %s", e)

    def stop(self) -> None:
        """Stop audio capture."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                pass
        logger.info("Audio capture stopped")

    def close(self) -> None:
        """Release audio resources."""
        self.stop()
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._buffer.stop()

    def _audio_callback(self, indata, frames, time_info, status):
        """Sounddevice callback - runs in audio thread."""
        if not self._running:
            return

        self._chunk_number += 1

        chunk = AudioChunk(
            data=indata.copy(),
            chunk_number=self._chunk_number,
            timestamp_ns=time.monotonic_ns(),
            wall_time=time.time(),
            sample_rate=self._sample_rate,
            channels=self._channels,
            samples=frames,
        )

        self._buffer.put(chunk)

    @property
    def sample_rate(self) -> int:
        """Actual sample rate (may differ from requested)."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Number of audio channels."""
        return self._channels

    @property
    def chunk_count(self) -> int:
        """Total chunks captured."""
        return self._chunk_number

    @property
    def is_running(self) -> bool:
        """True if audio capture is running."""
        return self._running
