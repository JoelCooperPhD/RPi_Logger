# Component Specifications

## Core Types

### CameraId

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class CameraId:
    backend: str          # "usb"
    stable_id: str        # Unique device identifier

    def __str__(self) -> str:
        return f"{self.backend}:{self.stable_id}"
```

### CameraDescriptor

```python
@dataclass
class CameraDescriptor:
    camera_id: CameraId
    name: str             # Human-readable name
    device_path: str      # /dev/video0
    usb_path: str | None  # USB bus:device path
```

### CaptureFrame

```python
@dataclass
class CaptureFrame:
    data: bytes           # Frame data (see format spec below)
    timestamp_mono: float # time.monotonic() - 9 decimal precision
    timestamp_unix: float # time.time() - 6 decimal precision
    frame_index: int      # Sequential frame number (1-based)
    width: int
    height: int
```

#### Data Format Specification

| pixel_format | `data` contents | Byte order | Size calculation |
|--------------|-----------------|------------|------------------|
| `MJPG` | JPEG-compressed bytes | N/A (self-contained) | Variable (typically 50-200KB at 720p) |
| `YUYV` | Raw YUV422 interleaved | Little-endian (native) | `width × height × 2` bytes |
| `BGR` | Raw BGR24 (after decode) | BGR order (OpenCV native) | `width × height × 3` bytes |

**MJPG format details**:
- Starts with `0xFF 0xD8` (JPEG SOI marker)
- Ends with `0xFF 0xD9` (JPEG EOI marker)
- Can be written directly to `.jpg` file

**Example MJPG header** (first 4 bytes):
```
FF D8 FF E0  # SOI + APP0 marker
```

**YUYV format details** (if camera doesn't support MJPG):
- Pixel pairs: `[Y0, U, Y1, V]` = 2 pixels in 4 bytes
- Convert to BGR: `cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_YUYV)`

### CapabilityMode

```python
@dataclass
class CapabilityMode:
    width: int
    height: int
    fps: float
    pixel_format: str     # "MJPG", "YUYV"
```

### CameraCapabilities

```python
@dataclass
class CameraCapabilities:
    modes: list[CapabilityMode]
    controls: dict[str, ControlInfo]
    default_preview: CapabilityMode | None
    default_record: CapabilityMode | None
    probed_at: float      # time.time() when probed
```

### ControlInfo

```python
@dataclass
class ControlInfo:
    name: str
    control_type: str     # "int", "bool", "menu"
    min_value: int | None
    max_value: int | None
    default_value: int | None
    step: int | None
    menu_items: dict[int, str] | None  # For menu type
```

---

## USBCapture Interface

```python
class USBCapture:
    def __init__(
        self,
        device_path: str,
        width: int,
        height: int,
        fps: float,
        pixel_format: str = "MJPG"
    ) -> None: ...

    async def start(self) -> None:
        """Start background capture thread."""

    async def stop(self) -> None:
        """Stop capture and release resources."""

    def __aiter__(self) -> AsyncIterator[CaptureFrame]:
        """Yield frames as they arrive."""

    @property
    def actual_fps(self) -> float:
        """FPS reported by camera (may differ from requested)."""

    @property
    def is_running(self) -> bool:
        """True if capture is active."""
```

### Queue Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max size | 3 frames | ~100ms buffer at 30fps |
| Overflow behavior | **Drop oldest** | Producer never blocks |
| Timeout | None | Async consumer uses `await queue.get()` |

### Queue Overflow Behavior

When queue is full and new frame arrives:
1. **Remove oldest frame** from queue (silent drop)
2. **Log warning** once per second: `"Frame queue overflow, dropping frames"`
3. **Increment drop counter** for metrics
4. **Put new frame** in queue

**Pseudocode**:
```python
def _on_frame_captured(self, frame: CaptureFrame) -> None:
    if self._queue.full():
        try:
            self._queue.get_nowait()  # Drop oldest
            self._drop_count += 1
            if time.monotonic() - self._last_drop_log > 1.0:
                logger.warning("Frame queue overflow, dropping frames")
                self._last_drop_log = time.monotonic()
        except Empty:
            pass
    self._queue.put_nowait(frame)
```

### Capture Loop Pseudocode

```python
def _read_loop(self) -> None:
    """Background thread - blocking reads from camera."""
    frame_index = 0
    while self._running:
        ret, raw_frame = self._cap.read()

        if not ret:
            self._error = DeviceLost(self._camera_id)
            break

        frame_index += 1
        frame = CaptureFrame(
            data=self._encode_frame(raw_frame),
            timestamp_mono=time.monotonic(),
            timestamp_unix=time.time(),
            frame_index=frame_index,
            width=raw_frame.shape[1],
            height=raw_frame.shape[0],
        )
        self._on_frame_captured(frame)

    self._cap.release()
```

### Async Iterator Pseudocode

```python
async def __anext__(self) -> CaptureFrame:
    """Yield frames to async consumer."""
    while self._running or not self._queue.empty():
        try:
            frame = await asyncio.wait_for(
                asyncio.to_thread(self._queue.get, timeout=0.1),
                timeout=0.2
            )
            return frame
        except (Empty, asyncio.TimeoutError):
            if self._error:
                raise self._error
            continue
    raise StopAsyncIteration
```

---

## USB Backend Interface

```python
async def probe(device_path: str) -> CameraCapabilities:
    """Discover camera capabilities.

    Raises:
        ProbeError: If device cannot be probed
        DeviceLost: If device disconnects during probe
    """

async def set_control(
    device_path: str,
    control_name: str,
    value: int
) -> None:
    """Set camera control value."""

async def get_control(
    device_path: str,
    control_name: str
) -> int:
    """Get current control value."""
```

---

## CamerasRuntime Interface

```python
class CamerasRuntime:
    def __init__(
        self,
        config: CamerasConfig,
        view: CameraView | None = None
    ) -> None: ...

    async def assign_device(
        self,
        camera_id: CameraId,
        descriptor: CameraDescriptor
    ) -> None:
        """Assign camera and start capture."""

    async def unassign_device(self) -> None:
        """Stop capture and release camera."""

    async def start_recording(
        self,
        session_prefix: str,
        trial_number: int
    ) -> None:
        """Begin recording to file."""

    async def stop_recording(self) -> None:
        """Stop recording and finalize files."""

    async def handle_command(
        self,
        command: str,
        payload: dict
    ) -> None:
        """Process supervisor command."""

    def push_frame_to_preview(
        self,
        frame: CaptureFrame
    ) -> None:
        """Send frame to UI preview."""
```

---

## CameraView Interface

```python
class CameraView:
    def __init__(
        self,
        parent: tk.Widget,
        on_settings: Callable[[], None],
        on_control_change: Callable[[str, int], None]
    ) -> None: ...

    def build_ui(self) -> None:
        """Create Tkinter widgets."""

    def push_frame(self, image_data: bytes, width: int, height: int) -> None:
        """Update preview with new frame.

        image_data format: Raw RGB24 bytes (not PPM)
        - Byte order: R, G, B, R, G, B, ... (row-major)
        - Size: width × height × 3 bytes
        - Convert to PhotoImage via PIL.Image.frombytes('RGB', (w, h), data)
        """

    def update_metrics(
        self,
        capture_fps: float,
        record_fps: float,
        queue_depth: int
    ) -> None:
        """Refresh metrics display."""

    def set_recording_state(self, recording: bool) -> None:
        """Update recording indicator."""
```

---

## Exceptions

```python
class CameraError(Exception):
    """Base exception for camera errors."""

class DeviceLost(CameraError):
    """Camera disconnected unexpectedly."""
    camera_id: CameraId

class ProbeError(CameraError):
    """Failed to probe camera capabilities."""
    device_path: str
    reason: str

class CaptureError(CameraError):
    """Frame capture failed."""

class EncoderError(CameraError):
    """Video encoding failed."""
```

### Error Recovery Matrix

| Exception | Where Raised | Recovery Action | State After |
|-----------|--------------|-----------------|-------------|
| `DeviceLost` | USBCapture._read_loop | Stop capture, notify runtime, attempt reconnect | IDLE |
| `ProbeError` | probe() | Log error, skip device | IDLE |
| `CaptureError` | USBCapture | Retry 3 times, then raise DeviceLost | IDLE if failed |
| `EncoderError` | Encoder.write_frame | Finalize partial file, stop recording | CAPTURING |

### Recovery Pseudocode

```python
async def _handle_device_lost(self, error: DeviceLost) -> None:
    """Handle camera disconnect during operation."""
    logger.error(f"Camera lost: {error.camera_id}")

    # 1. Stop capture cleanly
    if self._capture:
        await self._capture.stop()
        self._capture = None

    # 2. Finalize any recording
    if self._state == State.RECORDING:
        await self._finalize_recording(partial=True)

    # 3. Update state
    self._state = State.IDLE
    self._assigned_camera = None

    # 4. Notify UI
    if self._view:
        self._view.set_error_state("Camera disconnected")

    # 5. Attempt reconnect (optional)
    if self._config.auto_reconnect:
        asyncio.create_task(self._attempt_reconnect(error.camera_id))
```
