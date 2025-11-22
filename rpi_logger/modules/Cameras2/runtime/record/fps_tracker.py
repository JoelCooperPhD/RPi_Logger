"""Record FPS tracker."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass(slots=True)
class RecordFPSSnapshot:
    fps: float
    samples: int


class RecordFPSTracker:
    """Tracks effective recording FPS over a sliding window."""

    def __init__(self, window_size: int = 30) -> None:
        self._timestamps: Deque[float] = deque(maxlen=window_size)

    def record_frame(self, timestamp: float | None = None) -> RecordFPSSnapshot:
        ts = timestamp if timestamp is not None else time.time()
        self._timestamps.append(ts)
        fps = 0.0
        if len(self._timestamps) >= 2:
            delta = self._timestamps[-1] - self._timestamps[0]
            if delta > 0:
                fps = (len(self._timestamps) - 1) / delta
        return RecordFPSSnapshot(fps=fps, samples=len(self._timestamps))

    def reset(self) -> None:
        self._timestamps.clear()
