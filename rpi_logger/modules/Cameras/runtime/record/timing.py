"""Frame timing utilities for Cameras recording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class TimingUpdate:
    """Per-frame timing summary."""

    hardware_frame_number: Optional[int]
    sensor_timestamp_ns: int
    dropped_since_last: int
    total_hardware_drops: int


class FrameTimingTracker:
    """Lightweight drop tracker based on backend frame numbers."""

    def __init__(self) -> None:
        self._last_frame_number: Optional[int] = None
        self._total_drops: int = 0

    def reset(self) -> None:
        self._last_frame_number = None
        self._total_drops = 0

    def update(
        self,
        *,
        frame_number: Optional[int],
        sensor_timestamp: Optional[float],
        monotonic_time: float,
    ) -> TimingUpdate:
        """Update counters for one frame and return timing snapshot."""

        # Sensor timestamp in nanoseconds (fallback to monotonic clock).
        fallback_ts = monotonic_time if sensor_timestamp is None else sensor_timestamp
        ts_ns = int(fallback_ts * 1_000_000_000)

        # Normalize frame number and derive drops.
        current = frame_number
        if current is None:
            current = (self._last_frame_number or -1) + 1

        dropped = 0
        if self._last_frame_number is not None:
            delta = current - self._last_frame_number
            if delta > 1:
                dropped = delta - 1

        self._total_drops += max(0, dropped)
        self._last_frame_number = current

        return TimingUpdate(
            hardware_frame_number=current,
            sensor_timestamp_ns=ts_ns,
            dropped_since_last=dropped,
            total_hardware_drops=self._total_drops,
        )


__all__ = ["FrameTimingTracker", "TimingUpdate"]
