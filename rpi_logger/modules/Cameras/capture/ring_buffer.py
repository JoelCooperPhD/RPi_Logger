"""Thread-safe ring buffers with overwrite-on-full semantics."""

import asyncio
import threading
from collections import deque
from typing import AsyncIterator, Optional, TypeVar, Generic

from .frame import CapturedFrame, AudioChunk

T = TypeVar("T")


class RingBuffer(Generic[T]):
    """Generic fixed-size ring buffer with overwrite-on-full semantics."""

    def __init__(self, capacity: int = 8):
        self._buffer: deque[T] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._event: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._drops = 0
        self._stopped = False

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind to async event loop for signaling."""
        self._loop = loop
        self._event = asyncio.Event()

    def put(self, item: T) -> bool:
        """Add item (thread-safe). Returns False if dropped old item."""
        with self._lock:
            was_full = len(self._buffer) == self._buffer.maxlen
            if was_full:
                self._drops += 1
            self._buffer.append(item)

        # Signal async consumers
        if self._loop and self._event:
            self._loop.call_soon_threadsafe(self._event.set)

        return not was_full

    def get_latest(self) -> Optional[T]:
        """Get most recent item (thread-safe)."""
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    async def items(self) -> AsyncIterator[T]:
        """Async iterator yielding items as they arrive."""
        while not self._stopped:
            if self._event:
                await self._event.wait()
                self._event.clear()

            with self._lock:
                while self._buffer:
                    yield self._buffer.popleft()

    def stop(self) -> None:
        """Stop the buffer and wake any waiting consumers."""
        self._stopped = True
        if self._loop and self._event:
            self._loop.call_soon_threadsafe(self._event.set)

    def clear(self) -> None:
        """Clear all items from buffer."""
        with self._lock:
            self._buffer.clear()

    @property
    def drops(self) -> int:
        """Number of items dropped due to buffer full."""
        return self._drops

    @property
    def size(self) -> int:
        """Current number of items in buffer."""
        with self._lock:
            return len(self._buffer)


class FrameRingBuffer(RingBuffer[CapturedFrame]):
    """Ring buffer specialized for video frames."""

    async def frames(self) -> AsyncIterator[CapturedFrame]:
        """Async iterator yielding frames as they arrive."""
        async for frame in self.items():
            yield frame


class AudioRingBuffer(RingBuffer[AudioChunk]):
    """Ring buffer specialized for audio chunks."""

    async def chunks(self) -> AsyncIterator[AudioChunk]:
        """Async iterator yielding audio chunks as they arrive."""
        async for chunk in self.items():
            yield chunk
