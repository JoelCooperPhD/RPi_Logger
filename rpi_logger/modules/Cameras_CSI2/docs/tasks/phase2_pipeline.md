# Phase 2: Pipeline

> Frame routing and time-based FPS control

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Sub-tasks** | P2.1, P2.2, P2.3 |
| **Dependencies** | P1.1 (CapturedFrame), P1.4 (FrameBuffer) |
| **Effort** | Medium |
| **Key Specs** | [components.md](../specs/components.md) |

## Goal

Distribute frames from source to consumers with precise time-based FPS control.

---

## Sub-Tasks

### P2.1: TimingGate

**File**: `pipeline/timing_gate.py` (~80 lines)

Time-based frame selection (NOT frame counting).

```python
class TimingGate:
    def __init__(self, target_fps: float):
        self._target_interval_ns = int(1_000_000_000 / target_fps)
        self._next_target_ns = 0
        self._tolerance_ns = self._target_interval_ns // 10  # 10%

    def should_accept(self, frame: CapturedFrame) -> bool:
        """Return True if this frame should be accepted."""
        now = frame.monotonic_ns
        if self._next_target_ns == 0:
            self._next_target_ns = now + self._target_interval_ns
            return True
        if now >= self._next_target_ns - self._tolerance_ns:
            self._next_target_ns = now + self._target_interval_ns
            return True
        return False

    def reset(self) -> None: ...
    def set_target_fps(self, fps: float) -> None: ...

    @property
    def actual_fps(self) -> float: ...
    @property
    def skip_count(self) -> int: ...
```

**Key**: Anchor next target to actual accept time to prevent drift.

**Validation**:
- [ ] At 60fps input, 5fps target → accepts ~12th frame each time
- [ ] FPS accuracy within ±1%

---

### P2.2: FrameRouter

**File**: `pipeline/router.py` (~100 lines)

Distributes frames to multiple consumers.

```python
class FrameRouter:
    def __init__(self, source: FrameSource): ...

    def add_consumer(self, consumer: Callable, priority: int = 0) -> None: ...
    def remove_consumer(self, consumer: Callable) -> None: ...

    async def run(self) -> None:
        """Main distribution loop."""
        async for frame in self._source.frames():
            for consumer in sorted(self._consumers, key=priority):
                await consumer(frame)
```

**Priority order**:
1. Recording (highest) - never skip if recording
2. Metrics - always update
3. Preview (lowest) - can skip under load

**Validation**:
- [ ] Consumers called in priority order
- [ ] Handles consumer exceptions gracefully

---

### P2.3: FrameMetrics

**File**: `pipeline/metrics.py` (~80 lines)

Tracks timing statistics.

```python
class FrameMetrics:
    def update_capture(self, frame: CapturedFrame) -> None: ...
    def update_record(self, frame: CapturedFrame) -> None: ...
    def update_preview(self) -> None: ...
    def get_report(self) -> MetricsReport: ...

    @property
    def capture_fps(self) -> float: ...
    @property
    def record_fps(self) -> float: ...
    @property
    def preview_fps(self) -> float: ...
    @property
    def jitter_ns(self) -> int: ...
```

Use rolling window for FPS calculation (last 1 second).

**Validation**:
- [ ] FPS values are accurate
- [ ] Jitter calculation works

---

## Validation Checklist

- [ ] All 3 files created
- [ ] `__init__.py` exports all classes
- [ ] Unit test: TimingGate accepts at correct intervals
- [ ] Integration test: Route 1000 frames at 60fps, gate to 5fps
- [ ] Benchmark: <1% FPS deviation from target

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md).
