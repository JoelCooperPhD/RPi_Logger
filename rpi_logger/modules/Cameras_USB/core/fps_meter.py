"""Simple rolling window FPS calculator."""


class FPSMeter:
    """Rolling window FPS calculator."""

    def __init__(self, window_size: int = 30):
        """Initialize FPS meter.

        Args:
            window_size: Number of intervals to average over
        """
        self._intervals: list[float] = []
        self._window_size = window_size
        self._last_time = 0.0
        self._fps = 0.0

    def tick(self, now: float) -> float:
        """Record a tick and return current FPS.

        Args:
            now: Current timestamp (e.g., time.time() or wall_time)

        Returns:
            Current calculated FPS
        """
        if self._last_time > 0:
            interval = now - self._last_time
            if interval > 0:
                self._intervals.append(interval)
                if len(self._intervals) > self._window_size:
                    self._intervals.pop(0)
                if len(self._intervals) >= 3:
                    avg = sum(self._intervals) / len(self._intervals)
                    self._fps = 1.0 / avg if avg > 0 else 0.0
        self._last_time = now
        return self._fps

    @property
    def fps(self) -> float:
        """Current calculated FPS."""
        return self._fps

    def reset(self) -> None:
        """Reset meter state."""
        self._intervals.clear()
        self._last_time = 0.0
        self._fps = 0.0
