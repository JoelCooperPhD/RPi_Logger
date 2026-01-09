import asyncio
import time
from typing import AsyncIterator, Callable, Optional

import numpy as np

from .frame import AudioChunk
from .frame_buffer import AudioBuffer


class AudioSource:
    def __init__(
        self,
        device_index: int,
        sample_rate: int = 48000,
        channels: int = 2,
        chunk_size: int = 1024,
        buffer_capacity: int = 16,
    ):
        self._device_index = device_index
        self._sample_rate = sample_rate
        self._channels = channels
        self._chunk_size = chunk_size
        self._buffer = AudioBuffer(capacity=buffer_capacity)
        self._stream = None
        self._running = False
        self._chunk_number = 0
        self._on_error: Optional[Callable[[str], None]] = None

    def set_error_callback(self, callback: Callable[[str], None]) -> None:
        self._on_error = callback

    def open(self) -> bool:
        try:
            import sounddevice as sd
        except ImportError:
            if self._on_error:
                self._on_error("sounddevice not available")
            return False

        try:
            self._stream = sd.InputStream(
                device=self._device_index,
                samplerate=self._sample_rate,
                channels=self._channels,
                blocksize=self._chunk_size,
                dtype=np.float32,
                callback=self._audio_callback,
            )
            return True
        except Exception as e:
            if self._on_error:
                self._on_error(f"Failed to open audio device: {e}")
            return False

    def close(self) -> None:
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._buffer.stop()
        self._buffer.clear()

    def start_capture(self) -> None:
        if self._running:
            return
        if not self._stream:
            if not self.open():
                return
        self._running = True
        try:
            self._stream.start()
        except Exception as e:
            self._running = False
            if self._on_error:
                self._on_error(f"Failed to start audio: {e}")

    def stop_capture(self) -> None:
        self._running = False
        self._buffer.stop()
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                pass

    def _audio_callback(self, indata, frames, time_info, status):
        if not self._running:
            return

        if status:
            pass

        mono_ns = time.monotonic_ns()
        wall_time = time.time()

        self._chunk_number += 1

        chunk = AudioChunk(
            data=indata.copy(),
            chunk_number=self._chunk_number,
            capture_timestamp_ns=mono_ns,
            monotonic_ns=mono_ns,
            wall_time=wall_time,
            sample_rate=self._sample_rate,
            channels=self._channels,
            samples=frames,
        )

        self._buffer.put_overwrite(chunk)

    async def chunks(self) -> AsyncIterator[AudioChunk]:
        async for chunk in self._buffer.chunks():
            yield chunk

    async def get_chunk(self) -> Optional[AudioChunk]:
        return await self._buffer.get()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def chunk_count(self) -> int:
        return self._chunk_number

    @property
    def drops(self) -> int:
        return self._buffer.drops

    @property
    def is_running(self) -> bool:
        return self._running

    def configure(
        self,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
    ) -> bool:
        was_running = self._running
        if was_running:
            self.stop_capture()
            self.close()

        if sample_rate:
            self._sample_rate = sample_rate
        if channels:
            self._channels = channels

        if was_running:
            if self.open():
                self.start_capture()
                return True
            return False

        return True
