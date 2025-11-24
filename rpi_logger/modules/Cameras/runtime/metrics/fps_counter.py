"""Rolling FPS counters."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional


@dataclass(slots=True)
class FPSSnapshot:
    instant: float
    average: float
    sample_count: int
    last_timestamp: float


class FPSCounter:
    """Compute instantaneous and smoothed FPS."""

    def __init__(self, window_size: int = 30) -> None:
        self._window: Deque[float] = deque(maxlen=window_size)
        self._last_ts: Optional[float] = None

    def update(self, timestamp: Optional[float] = None) -> FPSSnapshot:
        now = timestamp if timestamp is not None else time.time()
        if self._last_ts is None:
            self._last_ts = now
            return FPSSnapshot(instant=0.0, average=0.0, sample_count=0, last_timestamp=now)

        delta = max(1e-6, now - self._last_ts)
        instant = 1.0 / delta
        self._last_ts = now

        self._window.append(instant)
        avg = sum(self._window) / len(self._window)
        return FPSSnapshot(instant=instant, average=avg, sample_count=len(self._window), last_timestamp=now)

    def reset(self) -> None:
        self._window.clear()
        self._last_ts = None
