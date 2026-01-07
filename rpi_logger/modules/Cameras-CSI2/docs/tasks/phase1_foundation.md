# Phase 1: Foundation

> Core data types and frame acquisition - the sacred capture loop

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Sub-tasks** | P1.1, P1.2, P1.3, P1.4 |
| **Dependencies** | None (can start immediately) |
| **Effort** | Medium |
| **Key Specs** | [components.md](../specs/components.md) |

## Goal

Establish the frame data model and ultra-tight capture loop that acquires frames from the camera with minimal overhead and accurate timestamps.

---

## Sub-Tasks

### P1.1: CapturedFrame Dataclass

**File**: `capture/frame.py` (~50 lines)

Create the immutable frame data container:

```python
@dataclass(frozen=True, slots=True)
class CapturedFrame:
    data: np.ndarray              # Raw frame (YUV420 or RGB)
    frame_number: int             # Sequential from camera start
    sensor_timestamp_ns: int      # Hardware sensor timestamp
    monotonic_ns: int             # time.monotonic_ns() at receipt
    wall_time: float              # time.time() at receipt
    color_format: str             # "yuv420" | "rgb" | "bgr"
    size: tuple[int, int]         # (width, height)
    metadata: dict                # Full picamera2 metadata
    sequence_number: int          # picamera2 sequence number
```

**Validation**:
- [ ] Dataclass is frozen (immutable)
- [ ] All timestamp fields present
- [ ] Type hints complete

---

### P1.2: FrameSource Protocol

**File**: `capture/source.py` (~40 lines)

Define the abstract interface for frame acquisition:

```python
from typing import Protocol, AsyncIterator

class FrameSource(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def frames(self) -> AsyncIterator[CapturedFrame]: ...

    @property
    def is_running(self) -> bool: ...
    @property
    def hardware_fps(self) -> float: ...
    @property
    def frame_count(self) -> int: ...
    @property
    def drop_count(self) -> int: ...
```

**Validation**:
- [ ] Protocol is runtime-checkable
- [ ] All properties documented

---

### P1.3: PicamSource Implementation

**File**: `capture/picam_source.py` (~200 lines)

Implement FrameSource for Picamera2. **This is the sacred capture loop.**

**Critical requirements**:
1. Use `capture_request()` NOT `capture_array()` - need metadata
2. Extract `SensorTimestamp` from metadata
3. Dedicated capture thread with highest priority
4. Lock-free handoff to async via ring buffer
5. Strict `FrameDurationLimits` (min=max)

**Capture thread pseudo-code**:
```python
while running:
    request = camera.capture_request()
    metadata = request.get_metadata()
    sensor_ts = metadata["SensorTimestamp"]
    mono_ns = time.monotonic_ns()
    wall = time.time()
    array = request.make_array("main")
    request.release()

    frame = CapturedFrame(array, sensor_ts, mono_ns, ...)

    if not buffer.try_put(frame):
        drop_count += 1
        # Log drop to ring buffer (not stdout!)
```

**Forbidden in capture thread**:
- Memory allocation (pre-allocate everything)
- Logging to file/stdout
- Any I/O except queue put
- Lock acquisition

**Validation**:
- [ ] Uses `capture_request()` with metadata
- [ ] `SensorTimestamp` extracted and propagated
- [ ] Dedicated thread for capture
- [ ] Drop counting works
- [ ] Benchmark: <100μs overhead per frame

---

### P1.4: Lock-Free Frame Buffer

**File**: `pipeline/frame_buffer.py` (~100 lines)

Ring buffer for thread → async handoff.

```python
class FrameBuffer:
    def __init__(self, capacity: int = 8): ...
    def try_put(self, frame: CapturedFrame) -> bool: ...
    async def frames(self) -> AsyncIterator[CapturedFrame]: ...

    @property
    def size(self) -> int: ...
    @property
    def capacity(self) -> int: ...
    @property
    def drops(self) -> int: ...
```

**Implementation notes**:
- Use `collections.deque` with maxlen for simplicity
- Or implement proper lock-free ring buffer
- `try_put` returns False if full (drop frame)
- `frames()` yields to async event loop

**Validation**:
- [ ] No blocking in `try_put()`
- [ ] Works with asyncio
- [ ] Handles backpressure (drops oldest or newest)

---

## Implementation Notes

### Picamera2 API Gotchas

See [picamera2_api.md](../reference/picamera2_api.md) for details.

**Wrong** (loses metadata):
```python
frame = camera.capture_array("main")
```

**Correct** (preserves metadata):
```python
request = camera.capture_request()
metadata = request.get_metadata()
frame = request.make_array("main")
request.release()
```

### Buffer Stride Padding

IMX296 returns 1536-wide buffers for 1456-wide images. Must crop after color conversion. See [hardware.md](../reference/hardware.md).

---

## Validation Checklist

- [ ] All 4 files created: `frame.py`, `source.py`, `picam_source.py`, `frame_buffer.py`
- [ ] `__init__.py` exports: `CapturedFrame`, `FrameSource`, `PicamSource`, `FrameBuffer`
- [ ] Unit test: CapturedFrame creation and immutability
- [ ] Integration test: Capture 100 frames, all have valid sensor timestamps
- [ ] Benchmark: Capture thread overhead <100μs per frame

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md):
1. Set P1.1-P1.4 status to `completed`
2. Add completion date and agent ID
3. Note any issues discovered
