"""Metrics helpers for Cameras runtime - FPS counters and timing trackers."""

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


__all__ = ["FPSCounter", "FPSSnapshot", "TimingSnapshot", "TimingTracker"]
