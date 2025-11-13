"""Frame timing utilities used by the Cameras runtime."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .constants import FRAME_LOG_COUNT


@dataclass(slots=True)
class TimingUpdate:
    """Lightweight summary of hardware timing info for a frame."""

    hardware_frame_number: Optional[int]
    sensor_timestamp_ns: Optional[int]
    expected_interval_ns: Optional[int]
    hardware_fps: float
    dropped_since_last: int


@dataclass(slots=True)
class FrameTimingResult:
    """Normalized timing data for a captured frame."""

    capture_index: int
    hardware_frame_number: Optional[int]
    dropped_since_last: Optional[int]
    sensor_timestamp_ns: Optional[int]
    timing_update: TimingUpdate


class FrameTimingCalculator:
    """Minimal frame timing tracker for detecting drops via sensor timestamps."""

    def __init__(self) -> None:
        self._hardware_frame_number = -1
        self._last_sensor_timestamp_ns: Optional[int] = None
        self._expected_interval_ns: Optional[int] = None
        self._hardware_fps: float = 0.0

    def reset(self) -> None:
        self._hardware_frame_number = -1
        self._last_sensor_timestamp_ns = None
        self._expected_interval_ns = None
        self._hardware_fps = 0.0

    def update(
        self,
        metadata: dict,
        *,
        captured_frames: int,
        logger,
        log_first_n: int = FRAME_LOG_COUNT,
    ) -> TimingUpdate:
        sensor_ts_ns = self._normalize_sensor_timestamp(metadata)
        expected_interval_ns = self._derive_expected_interval(metadata)
        dropped = 0

        if expected_interval_ns:
            self._expected_interval_ns = expected_interval_ns
            if expected_interval_ns > 0:
                self._hardware_fps = 1_000_000_000 / expected_interval_ns

        increment = 1
        if (
            sensor_ts_ns is not None
            and self._last_sensor_timestamp_ns is not None
            and self._expected_interval_ns
            and self._expected_interval_ns > 0
        ):
            delta = sensor_ts_ns - self._last_sensor_timestamp_ns
            if delta >= 0:
                expected_frames = max(1, round(delta / self._expected_interval_ns))
                increment = expected_frames
                dropped = max(0, expected_frames - 1)

        if self._hardware_frame_number < 0:
            self._hardware_frame_number = max(0, captured_frames)
        else:
            self._hardware_frame_number += increment

        hardware_frame_number = self._hardware_frame_number
        metadata['HardwareFrameNumber'] = hardware_frame_number
        metadata['DroppedSinceLast'] = dropped
        metadata.setdefault('SensorTimestamp', sensor_ts_ns)

        self._last_sensor_timestamp_ns = sensor_ts_ns

        if log_first_n and captured_frames < log_first_n:
            logger.info(
                "Frame %d timing -> sensor_ts=%s expected_interval=%s dropped=%s",
                captured_frames,
                sensor_ts_ns,
                self._expected_interval_ns,
                dropped,
            )

        return TimingUpdate(
            hardware_frame_number=hardware_frame_number,
            sensor_timestamp_ns=sensor_ts_ns,
            expected_interval_ns=self._expected_interval_ns,
            hardware_fps=self._hardware_fps,
            dropped_since_last=dropped,
        )

    def _normalize_sensor_timestamp(self, metadata: dict) -> Optional[int]:
        sensor_ts = metadata.get('SensorTimestamp')
        if isinstance(sensor_ts, (int, float)):
            return int(sensor_ts)
        # Picamera2 sometimes exposes timestamp in microseconds
        sensor_ts_us = metadata.get('SensorTimestampUsec')
        if isinstance(sensor_ts_us, (int, float)):
            return int(sensor_ts_us * 1000)
        # Fall back to monotonic time to keep counters moving
        return time.monotonic_ns()

    def _derive_expected_interval(self, metadata: dict) -> Optional[int]:
        frame_duration = metadata.get('FrameDuration') or metadata.get('FrameDurationUsec')
        if isinstance(frame_duration, (int, float)):
            # Picamera2 reports microseconds; convert to nanoseconds
            return int(frame_duration * 1000)
        frame_time = metadata.get('FrameTime')
        if isinstance(frame_time, (int, float)) and frame_time > 0:
            return int(frame_time)
        return None


class FrameTimingTracker:
    """Adapter that mirrors the production calculator interface for the Cameras runtime."""

    def __init__(self) -> None:
        self._calculator = FrameTimingCalculator()

    def reset(self) -> None:
        self._calculator.reset()

    def next(self, metadata: Optional[dict], *, capture_index: int, logger, log_first_n: int = FRAME_LOG_COUNT) -> FrameTimingResult:
        if metadata is None:
            metadata = {}

        timing_update = self._calculator.update(
            metadata,
            captured_frames=capture_index,
            logger=logger,
            log_first_n=log_first_n,
        )

        metadata['CaptureFrameIndex'] = capture_index

        return FrameTimingResult(
            capture_index=capture_index,
            hardware_frame_number=metadata.get('HardwareFrameNumber'),
            dropped_since_last=metadata.get('DroppedSinceLast'),
            sensor_timestamp_ns=timing_update.sensor_timestamp_ns,
            timing_update=timing_update,
        )


__all__ = ['FrameTimingResult', 'FrameTimingTracker', 'FrameTimingCalculator', 'TimingUpdate']
