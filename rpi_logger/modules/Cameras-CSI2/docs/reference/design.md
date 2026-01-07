# Design Principles

> Philosophy and constraints guiding implementation

## Coding Standards

**All code must follow these constraints**:

| Requirement | Rationale |
|-------------|-----------|
| **Modern asyncio patterns** | Use `async/await`, not threads (except capture loop) |
| **Non-blocking I/O** | All file/network I/O via `asyncio.to_thread()` or async libs |
| **No docstrings** | Skip docstrings and obvious comments |
| **Concise code** | Optimize for AI readability (context/token efficiency) |
| **Type hints** | Use type hints for self-documenting code |
| **Minimal abstractions** | Only abstract when reuse is proven, not speculative |

**Exception**: The capture thread uses a dedicated thread for lowest-latency frame acquisition. This is the ONLY place threads are allowed.

## 1. The Capture Loop Is Sacred

The frame acquisition thread does ONE thing: pull frames from the camera as fast as possible.

**Allowed in capture thread**:
- `capture_request()` call
- Timestamp extraction from metadata
- Single atomic queue put

**Forbidden in capture thread**:
- Memory allocation
- Logging (except to pre-allocated ring buffer)
- Any I/O except the queue put
- Lock acquisition (use lock-free structures)
- Business logic decisions

---

## 2. Timestamps Are Non-Negotiable

Every frame carries THREE timestamps:

| Timestamp | Type | Source | Purpose |
|-----------|------|--------|---------|
| Sensor timestamp | int (ns) | Hardware | When sensor actually captured |
| Monotonic timestamp | int (ns) | `time.monotonic_ns()` | Interval analysis |
| Wall clock | float (s) | `time.time()` | Absolute time correlation |

The sensor timestamp is the **ground truth** for when a frame was captured. Software timestamps are supplementary.

---

## 3. Time-Based Frame Selection

Preview and recording FPS are achieved via **time-based gating**, not frame counting.

```
Target: 5 FPS = 200ms intervals
Frame arrives at T=0ms    -> ACCEPT (first frame)
Frame arrives at T=16ms   -> SKIP (too soon)
Frame arrives at T=33ms   -> SKIP (too soon)
...
Frame arrives at T=198ms  -> SKIP (almost, but wait)
Frame arrives at T=215ms  -> ACCEPT (closest to 200ms target)
Next target: T=415ms (anchored to actual accept time)
```

**Why not frame counting?**
- Hardware may deliver frames unevenly
- Frame counting (every Nth frame) drifts from target FPS
- Time-based selection adapts to actual frame timing

---

## 4. Explicit Over Implicit

- **No silent frame drops** - every drop is logged with timestamp and reason
- **No default values buried in code** - all constants in config
- **No magic numbers** - all timing values derived from configuration
- **No hidden state** - component state is inspectable

---

## 5. Composition Over Inheritance

The runtime is composed of focused collaborators:

| Component | Responsibility | Dependencies |
|-----------|----------------|--------------|
| `FrameSource` | Just acquires frames | Camera hardware |
| `FrameRouter` | Distributes to consumers | FrameSource |
| `TimingGate` | Enforces FPS constraints | None (stateless) |
| `Recorder` | Writes to disk | TimingGate |
| `Previewer` | Feeds the UI | TimingGate |

Each component:
- Has a single responsibility
- Is independently testable
- Has no knowledge of other components' internals

---

## 6. Priority Hierarchy

When resources are constrained, components have explicit priority:

1. **Capture** (highest) - never skip, never block
2. **Recording** - next highest when active
3. **Metrics** - always update for monitoring
4. **Preview** (lowest) - can drop freely under load

---

## 7. Fail Transparently

When something goes wrong:
- Log the error with context
- Continue if possible
- Report via status message
- Never crash silently

Example: Camera disconnect during recording
1. Detect via frame timeout
2. Log error with last known state
3. Stop recording gracefully
4. Send `device_error` status
5. Attempt reconnection

---

## 8. Testability First

Every component must be:
- Unit testable in isolation
- Mockable at integration boundaries
- Benchmarkable for performance

Test coverage requirements:
- Core data types: 100%
- Frame pipeline: 90%
- Recording: 80%
- UI: 60% (harder to test)

---

## 9. Standalone Testing

During development, test components without the full logger system:

```bash
# Run from Logger root directory
cd /home/rs-pi-2/Development/Logger
PYTHONPATH=. python3 -c "
from rpi_logger.modules.Cameras_CSI2.capture.frame import CapturedFrame
import numpy as np

frame = CapturedFrame(
    data=np.zeros((1088, 1536), dtype=np.uint8),
    frame_number=1,
    sensor_timestamp_ns=1234567890,
    monotonic_ns=9876543210,
    wall_time=1704567890.123,
    color_format='yuv420',
    size=(1456, 1088),
    metadata={},
    sequence_number=1
)
print(f'Created frame: {frame.frame_number}, ts={frame.sensor_timestamp_ns}')
"

# Run unit tests
PYTHONPATH=. pytest rpi_logger/modules/Cameras_CSI2/tests/unit/ -v

# Quick hardware test (requires camera)
PYTHONPATH=. python3 -c "
from rpi_logger.modules.Cameras_CSI2.capture.picam_source import PicamSource
import asyncio

async def test():
    source = PicamSource(camera_index=0)
    await source.start()
    count = 0
    async for frame in source.frames():
        print(f'Frame {frame.frame_number}: sensor_ts={frame.sensor_timestamp_ns}')
        count += 1
        if count >= 10:
            break
    await source.stop()

asyncio.run(test())
"
```

**Note**: Module folder uses underscore (`Cameras_CSI2`) for Python imports but hyphen (`Cameras-CSI2`) in filesystem. Use underscore in import statements.
