"""Video FPS tracking utilities for Cameras storage pipelines."""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Optional


class VideoFpsTracker:
    """Tracks video frame cadence for both hardware and software encoders."""

    def __init__(self, sample_window: int = 240) -> None:
        self._sample_window = max(2, sample_window)
        self._hardware_samples: Deque[float] = deque(maxlen=self._sample_window)
        self._frame_count = 0
        self._start_monotonic: Optional[float] = None
        self._hardware_tracking = False

    # ------------------------------------------------------------------
    # Lifecycle helpers

    def reset(self) -> None:
        self._hardware_samples.clear()
        self._frame_count = 0
        self._start_monotonic = None
        self._hardware_tracking = False

    def start_hardware_tracking(self) -> None:
        self._hardware_tracking = True
        self._hardware_samples.clear()

    def stop_hardware_tracking(self) -> None:
        self._hardware_tracking = False
        self._hardware_samples.clear()

    # ------------------------------------------------------------------
    # Recording helpers

    def record_software_frame(self) -> None:
        """Record a frame written via the software video writer."""
        self._mark_frame()

    def record_hardware_frame(self) -> None:
        """Record a frame reported by the Picamera2 post-callback."""
        if not self._hardware_tracking:
            self.record_fallback_hardware_frame()
            return
        now = self._mark_frame()
        self._hardware_samples.append(now)

    def record_fallback_hardware_frame(self) -> None:
        """Record a hardware frame when post-callback timestamps are unavailable."""
        self._mark_frame()

    # ------------------------------------------------------------------
    # Observability

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def hardware_tracking(self) -> bool:
        return self._hardware_tracking

    def output_fps(self) -> float:
        if self._hardware_tracking and len(self._hardware_samples) >= 2:
            elapsed = self._hardware_samples[-1] - self._hardware_samples[0]
            if elapsed > 0:
                return (len(self._hardware_samples) - 1) / elapsed
        if self._frame_count == 0 or self._start_monotonic is None:
            return 0.0
        elapsed = max(time.monotonic() - self._start_monotonic, 1e-3)
        return self._frame_count / elapsed

    # ------------------------------------------------------------------
    # Internal helpers

    def _mark_frame(self) -> float:
        now = time.monotonic()
        self._frame_count += 1
        if self._start_monotonic is None:
            self._start_monotonic = now
        return now


__all__ = ["VideoFpsTracker"]
