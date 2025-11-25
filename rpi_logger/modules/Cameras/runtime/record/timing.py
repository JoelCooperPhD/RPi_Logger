"""Frame timing tracker for recordings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class FrameTimingUpdate:
    frame_number: int
    write_time_unix: float
    monotonic_time_ns: int
    sensor_timestamp_ns: Optional[int]
    hardware_frame_number: Optional[int]
    dropped_since_last: Optional[int]
    total_hardware_drops: int
    storage_queue_drops: int


def normalize_timestamp_ns(sensor_ts: Optional[int], monotonic_ts: int) -> int:
    """Normalize a sensor timestamp to nanoseconds near the provided monotonic value."""

    if sensor_ts is None or sensor_ts <= 0:
        return monotonic_ts

    candidates = [int(sensor_ts)]
    try:
        candidates.append(int(sensor_ts * 1000))
    except Exception:
        pass
    try:
        candidates.append(int(sensor_ts / 1000))
    except Exception:
        pass

    best = candidates[0]
    best_delta = abs(best - monotonic_ts)
    for cand in candidates[1:]:
        delta = abs(cand - monotonic_ts)
        if delta < best_delta:
            best = cand
            best_delta = delta
    return best


class FrameTimingTracker:
    """Track normalized timestamps and detect drops."""

    def __init__(self) -> None:
        self._last_frame_number: Optional[int] = None
        self._total_hw_drops = 0
        self._storage_queue_drops = 0

    def update(
        self,
        *,
        frame_number: int,
        sensor_timestamp_ns: Optional[int],
        monotonic_time_ns: int,
        write_time_unix: float,
        hardware_frame_number: Optional[int] = None,
        storage_queue_drops: int = 0,
    ) -> FrameTimingUpdate:
        normalized_ts = normalize_timestamp_ns(sensor_timestamp_ns, monotonic_time_ns)
        dropped_since_last: Optional[int] = None
        if self._last_frame_number is not None and frame_number > self._last_frame_number + 1:
            dropped_since_last = frame_number - self._last_frame_number - 1
            self._total_hw_drops += dropped_since_last
        self._last_frame_number = frame_number
        self._storage_queue_drops += max(0, storage_queue_drops)

        return FrameTimingUpdate(
            frame_number=frame_number,
            write_time_unix=write_time_unix,
            monotonic_time_ns=monotonic_time_ns,
            sensor_timestamp_ns=normalized_ts,
            hardware_frame_number=hardware_frame_number,
            dropped_since_last=dropped_since_last,
            total_hardware_drops=self._total_hw_drops,
            storage_queue_drops=self._storage_queue_drops,
        )


__all__ = ["FrameTimingTracker", "FrameTimingUpdate", "normalize_timestamp_ns"]
