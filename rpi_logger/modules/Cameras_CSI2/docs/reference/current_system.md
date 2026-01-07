# Current System Analysis

> What works, what's broken, and why we're rebuilding

## What Works

| Component | Assessment |
|-----------|------------|
| Layered architecture | Good separation between hardware/runtime/view |
| Base class reuse | Excellent inheritance from `rpi_logger.modules.base` |
| Capability validation | `CapabilityValidator` is well-designed |
| Output format | AVI/MJPEG + timing CSV meets requirements |
| Settings persistence | `KnownCamerasCache` works well |

---

## Critical Problems

### 1. Timestamp Inaccuracy

**Current**: Timestamps taken AFTER `capture_array()` returns

```python
# capture.py - WRONG
frame_data = self._cam.capture_array("main")  # Blocks for frame
monotonic_ns = time.monotonic_ns()  # Timestamp is late!
```

**Impact**: Timestamps include variable transfer time (1-5ms jitter)

**Required**: Use `capture_request()` with metadata to get `SensorTimestamp`

---

### 2. Sensor Timestamp Not Propagated

**Current**: Metadata passed as empty dict `{}`

```python
# Loses hardware timestamp!
loop.call_soon_threadsafe(enqueue_frame, queue,
    (frame_data, monotonic_ns, wall_time, {}, frame_data, frame_num))
```

**Required**: Extract and propagate `SensorTimestamp` from picamera2 metadata

---

### 3. FPS Control Is Approximate

**Current**: `FrameDurationLimits` allows ±5-10ms tolerance

```python
min_duration = max(1000, frame_duration_us - 5000)  # -5ms
max_duration = frame_duration_us + 10000  # +10ms
```

**Impact**: At 60 FPS (16.67ms frames), this is ±30-60% variance!

**Required**: Strict limits OR software-gated frame selection with timing compensation

---

### 4. Preview Decimation Is Frame-Count Based

**Current**: Every Nth frame regardless of timing

```python
if frame_count % preview_interval == 0:  # Not time-based!
```

**Impact**: If hardware delivers frames unevenly, preview timing is wrong

**Required**: Time-based frame selection for both preview and recording

---

### 5. God Class Problem

**Current**: `CSICamerasRuntime` is 879 lines handling 7+ responsibilities:
- Camera initialization
- Frame capture
- Preview processing
- Recording control
- Settings management
- Command handling
- Status reporting

**Required**: Decompose into focused, testable components

---

### 6. Silent Frame Drops

**Current**: Queue overflow silently discards frames

```python
except asyncio.QueueFull:
    pass  # Silent drop!
```

**Required**: Log every drop with timestamp and reason

---

## Why Rebuild vs. Refactor

| Approach | Pros | Cons |
|----------|------|------|
| Refactor in place | Less work | Hard to maintain invariants during transition |
| Rebuild alongside | Clean slate, can compare | More initial work |

**Decision**: Rebuild alongside (Cameras-CSI2)

Reasons:
1. Current code is too tangled to refactor incrementally
2. Can run both modules side-by-side for comparison
3. Can validate output format compatibility
4. Rollback is simple (just use old module)

---

## Compatibility Requirements

The new module MUST produce identical output:

| Aspect | Requirement |
|--------|-------------|
| CSV header | Byte-for-byte identical |
| CSV column formats | Exact decimal precision |
| Video format | MJPEG/AVI, same quality |
| Directory structure | Same paths |
| GUI appearance | Visually identical |
| Command protocol | Same commands and responses |
