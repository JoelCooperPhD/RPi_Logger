import asyncio
from collections import deque
from typing import AsyncIterator

from .frame import CapturedFrame


class FrameBuffer:
    def __init__(self, capacity: int = 8):
        self._capacity = capacity
        self._buffer: deque[CapturedFrame] = deque(maxlen=capacity)
        self._drops = 0
        self._event = asyncio.Event()
        self._running = False

    def try_put(self, frame: CapturedFrame) -> bool:
        if len(self._buffer) >= self._capacity:
            self._drops += 1
            return False
        self._buffer.append(frame)
        self._event.set()
        return True

    def put_overwrite(self, frame: CapturedFrame) -> bool:
        dropped = len(self._buffer) >= self._capacity
        if dropped:
            self._drops += 1
        self._buffer.append(frame)
        self._event.set()
        return not dropped

    async def get(self) -> CapturedFrame | None:
        while self._running or len(self._buffer) > 0:
            if len(self._buffer) > 0:
                return self._buffer.popleft()
            self._event.clear()
            try:
                await asyncio.wait_for(self._event.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
        return None

    async def frames(self) -> AsyncIterator[CapturedFrame]:
        self._running = True
        try:
            while self._running:
                if len(self._buffer) > 0:
                    yield self._buffer.popleft()
                else:
                    self._event.clear()
                    try:
                        await asyncio.wait_for(self._event.wait(), timeout=0.05)
                    except asyncio.TimeoutError:
                        continue
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        self._event.set()

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
