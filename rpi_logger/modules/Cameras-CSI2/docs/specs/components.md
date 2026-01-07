# Component Specifications

> Core data types and interfaces

## CapturedFrame

The fundamental data unit - immutable after creation.

```python
@dataclass(frozen=True, slots=True)
class CapturedFrame:
    data: np.ndarray              # Raw frame (YUV420 or RGB)
    frame_number: int             # Sequential from camera start
    sensor_timestamp_ns: int      # Hardware sensor timestamp (nanoseconds)
    monotonic_ns: int             # time.monotonic_ns() at receipt
    wall_time: float              # time.time() at receipt
    color_format: str             # "yuv420" | "rgb" | "bgr"
    size: tuple[int, int]         # (width, height)
    metadata: dict                # Full picamera2 metadata dict
    sequence_number: int          # picamera2 sequence number
```

**Immutability**: Once created, a CapturedFrame is never modified. Processing creates new frames.

---

## FrameSource

Abstract protocol for frame acquisition.

```python
class FrameSource(Protocol):
    async def start() -> None
    async def stop() -> None
    async def frames() -> AsyncIterator[CapturedFrame]

    @property
    def is_running() -> bool
    @property
    def hardware_fps() -> float      # Actual sensor frame rate
    @property
    def frame_count() -> int         # Total frames delivered
    @property
    def drop_count() -> int          # Frames dropped at source
```

---

## PicamSource

Picamera2 implementation of FrameSource.

**Critical Implementation Details**:

1. **Use `capture_request()` not `capture_array()`** to access metadata
2. **Extract `SensorTimestamp` from metadata** before yielding frame
3. **Dedicated capture thread** with highest priority
4. **Lock-free handoff** to async world via ring buffer
5. **Strict `FrameDurationLimits`** - set min=max for consistent intervals

```python
class PicamSource:
    _camera: Picamera2
    _buffer: FrameBuffer           # Lock-free ring buffer
    _capture_thread: Thread        # Dedicated capture thread
    _running: bool
    _frame_count: int
    _drop_count: int               # Frames dropped due to buffer full
    _drop_log: RingBuffer[DropEvent]  # Recent drop timestamps
```

---

## FrameRouter

Distributes frames from FrameBuffer to multiple consumers.

```python
class FrameRouter:
    _buffer: FrameBuffer           # Consumes from FrameBuffer, NOT FrameSource
    _record_gate: TimingGate       # Gate for recording FPS
    _preview_gate: TimingGate      # Gate for preview FPS
    _metrics: FrameMetrics

    async def run(self) -> None:
        async for frame in self._buffer.frames():
            self._metrics.update_capture(frame)

            if self._recording and self._record_gate.should_accept(frame):
                await self._recording_session.write_frame(frame)
                self._metrics.update_record(frame)

            if self._preview_gate.should_accept(frame):
                preview_data = self._preview_processor.process(frame)
                if preview_data:
                    self._view.push_frame(preview_data)
                    self._metrics.update_preview()
```

**Priority order** (implicit in loop structure):
1. Recording - checked first when active
2. Metrics - always update
3. Preview - gated separately, can drop under load

---

## TimingGate

Enforces target FPS via time-based frame selection.

```python
class TimingGate:
    _target_fps: float
    _target_interval_ns: int       # Computed: 1e9 / target_fps
    _last_accept_ns: int           # Monotonic time of last accepted frame
    _tolerance_ns: int             # Acceptable early arrival (default: 10%)

    def should_accept(frame: CapturedFrame) -> bool
    def reset() -> None                # Reset timing (e.g., on recording start)
    def set_target_fps(fps: float) -> None

    @property
    def actual_fps -> float            # Measured output FPS
    @property
    def skip_count -> int              # Frames skipped since reset
```

**Algorithm**:
```python
def should_accept(frame):
    now = frame.monotonic_ns

    # First frame always accepted
    if self._next_target_ns == 0:
        self._next_target_ns = now + self._target_interval_ns
        return True

    # Check if we've reached (or passed) the target time
    if now >= self._next_target_ns - self._tolerance_ns:
        # Anchor to actual accept time to prevent drift
        self._next_target_ns = now + self._target_interval_ns
        return True

    return False
```

---

## RecordingSession

Manages a single recording session. **Note**: FPS gating is done by FrameRouter, not RecordingSession.

```python
class RecordingSession:
    _encoder: VideoEncoder
    _timing_writer: TimingCSVWriter
    _session_dir: Path
    _trial_number: int
    _camera_id: CameraId
    _is_recording: bool
    _frame_count: int
    _start_time: float

    async def start(self, session_dir: Path, trial_number: int, camera_id: str) -> None
    async def stop(self) -> RecordingMetrics
    async def write_frame(self, frame: CapturedFrame) -> None  # Called by FrameRouter after gating

    @property
    def is_recording(self) -> bool: ...
    @property
    def frame_count(self) -> int: ...
```

---

## FrameMetrics

Tracks timing statistics for monitoring.

```python
class FrameMetrics:
    _capture_fps: RollingAverage   # Actual capture rate
    _record_fps: RollingAverage    # Actual recording rate
    _preview_fps: RollingAverage   # Actual preview rate
    _frame_intervals: RollingStats # Frame interval statistics
    _jitter_ns: int                # Max deviation from target interval

    def update_capture(frame: CapturedFrame) -> None
    def update_record(frame: CapturedFrame) -> None
    def update_preview() -> None
    def get_report() -> MetricsReport
```

---

## PreviewProcessor

Prepares frames for display.

```python
class PreviewProcessor:
    _gate: TimingGate              # For target preview FPS
    _scaler: FrameScaler
    _target_size: tuple[int, int]  # Canvas size
    _color_convert: bool           # YUV420 -> RGB needed?

    def process(frame: CapturedFrame) -> Optional[bytes]  # PPM data or None
    def set_target_size(width, height) -> None
    def set_target_fps(fps: float) -> None
```

---

## FrameBuffer

Lock-free ring buffer for thread→async handoff.

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
