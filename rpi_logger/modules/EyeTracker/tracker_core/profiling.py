"""Lightweight profiling for frame processing pipeline."""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class PhaseMetrics:
    """Metrics for a single processing phase."""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))

    def record(self, duration_ms: float) -> None:
        self.samples.append(duration_ms)

    @property
    def mean_ms(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.samples) if self.samples else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]


class FrameProfiler:
    """
    Lightweight profiler for frame processing pipeline.

    Usage:
        profiler = FrameProfiler()

        with profiler.measure('acquire'):
            frame = await stream_handler.wait_for_frame()

        with profiler.measure('process'):
            processed = frame_processor.process_frame(frame)

        # Get report
        print(profiler.report())
    """

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._phases: Dict[str, PhaseMetrics] = {}
        self._frame_count = 0
        self._start_time = time.perf_counter()

    def measure(self, phase: str):
        """Context manager for measuring a phase."""
        return _PhaseMeasurer(self, phase) if self._enabled else _NullMeasurer()

    def record(self, phase: str, duration_ms: float) -> None:
        """Record a duration for a phase."""
        if not self._enabled:
            return
        if phase not in self._phases:
            self._phases[phase] = PhaseMetrics()
        self._phases[phase].record(duration_ms)

    def tick_frame(self) -> None:
        """Call once per frame to track frame count."""
        self._frame_count += 1

    def report(self) -> Dict:
        """Generate profiling report."""
        elapsed = time.perf_counter() - self._start_time
        return {
            'elapsed_seconds': elapsed,
            'frame_count': self._frame_count,
            'effective_fps': self._frame_count / elapsed if elapsed > 0 else 0,
            'phases': {
                name: {
                    'mean_ms': metrics.mean_ms,
                    'max_ms': metrics.max_ms,
                    'p95_ms': metrics.p95_ms,
                    'samples': len(metrics.samples),
                }
                for name, metrics in self._phases.items()
            }
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self._phases.clear()
        self._frame_count = 0
        self._start_time = time.perf_counter()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value


class _PhaseMeasurer:
    """Context manager for phase measurement."""

    __slots__ = ('_profiler', '_phase', '_start')

    def __init__(self, profiler: FrameProfiler, phase: str):
        self._profiler = profiler
        self._phase = phase
        self._start: float = 0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        duration_ms = (time.perf_counter() - self._start) * 1000
        self._profiler.record(self._phase, duration_ms)


class _NullMeasurer:
    """No-op context manager when profiling disabled."""

    __slots__ = ()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
