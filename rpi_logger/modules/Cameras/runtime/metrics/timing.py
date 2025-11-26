"""Frame timing metrics."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Deque
from collections import deque


@dataclass(slots=True)
class TimingSnapshot:
    avg_latency_ms: float
    max_latency_ms: float
    samples: int


class TimingTracker:
    """Tracks latency measurements and exposes aggregates."""

    def __init__(self, window_size: int = 50) -> None:
        self._latencies: Deque[float] = deque(maxlen=window_size)

    def record(self, start_ts: float, end_ts: float | None = None) -> TimingSnapshot:
        end = end_ts if end_ts is not None else time.time()
        latency_ms = max(0.0, (end - start_ts) * 1000)
        self._latencies.append(latency_ms)
        avg = sum(self._latencies) / len(self._latencies)
        return TimingSnapshot(avg_latency_ms=avg, max_latency_ms=max(self._latencies), samples=len(self._latencies))

    def reset(self) -> None:
        self._latencies.clear()
