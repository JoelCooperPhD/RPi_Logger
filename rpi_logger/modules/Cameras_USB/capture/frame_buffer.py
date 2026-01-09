import asyncio
from collections import deque
from typing import AsyncIterator, TypeVar, Generic

from .frame import CapturedFrame, AudioChunk


T = TypeVar("T", CapturedFrame, AudioChunk)


class Buffer(Generic[T]):
    def __init__(self, capacity: int = 8):
        self._capacity = capacity
        self._buffer: deque[T] = deque(maxlen=capacity)
        self._drops = 0
        self._event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    def _get_event(self) -> asyncio.Event:
        if self._event is None:
            self._event = asyncio.Event()
            self._loop = asyncio.get_event_loop()
        return self._event

    def _signal_event(self) -> None:
        if self._event and self._loop:
            try:
                self._loop.call_soon_threadsafe(self._event.set)
            except RuntimeError:
                pass

    def try_put(self, item: T) -> bool:
        if len(self._buffer) >= self._capacity:
            self._drops += 1
            return False
        self._buffer.append(item)
        self._signal_event()
        return True

    def put_overwrite(self, item: T) -> bool:
        dropped = len(self._buffer) >= self._capacity
        if dropped:
            self._drops += 1
        self._buffer.append(item)
        self._signal_event()
        return not dropped

    async def get(self) -> T | None:
        event = self._get_event()
        while self._running or len(self._buffer) > 0:
            if len(self._buffer) > 0:
                return self._buffer.popleft()
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
        return None

    async def items(self) -> AsyncIterator[T]:
        event = self._get_event()
        self._running = True
        try:
            while self._running:
                if len(self._buffer) > 0:
                    yield self._buffer.popleft()
                else:
                    event.clear()
                    try:
                        await asyncio.wait_for(event.wait(), timeout=0.05)
                    except asyncio.TimeoutError:
                        continue
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        self._signal_event()

    def clear(self) -> None:
        self._buffer.clear()

    @property
    def size(self) -> int:
        return len(self._buffer)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def drops(self) -> int:
        return self._drops


class FrameBuffer(Buffer[CapturedFrame]):
    async def frames(self) -> AsyncIterator[CapturedFrame]:
        async for frame in self.items():
            yield frame


class AudioBuffer(Buffer[AudioChunk]):
    async def chunks(self) -> AsyncIterator[AudioChunk]:
        async for chunk in self.items():
            yield chunk
