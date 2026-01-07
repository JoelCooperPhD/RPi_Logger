# Phase 2: Capture Pipeline

## Quick Reference

| Task | Status | Dependencies | Effort | Spec |
|------|--------|--------------|--------|------|
| P2.1 USB capture class | available | P1.1, P1.3 | Medium | `specs/components.md` |
| P2.2 Frame queue system | available | P2.1 | Small | `reference/architecture.md` |
| P2.3 Capture loop async | available | P2.1, P2.2 | Medium | `reference/architecture.md` |

## Goal

Build robust frame capture pipeline with async consumer pattern.

---

## P2.1: USB Capture Class

### Deliverables

| File | Contents |
|------|----------|
| `camera_core/capture.py` | USBCapture class |

### Implementation

```python
# camera_core/capture.py
import asyncio
import time
import threading
from queue import Queue, Full
import cv2
from .types import CaptureFrame

class USBCapture:
    QUEUE_SIZE = 3

    def __init__(
        self,
        device_path: str,
        width: int,
        height: int,
        fps: float,
        pixel_format: str = "MJPG"
    ):
        self._device_path = device_path
        self._width = width
        self._height = height
        self._fps = fps
        self._pixel_format = pixel_format
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._queue: Queue[CaptureFrame | None] = Queue(maxsize=self.QUEUE_SIZE)
        self._frame_index = 0
        self._actual_fps = 0.0
        self._running = False

    async def start(self) -> None:
        self._cap = cv2.VideoCapture(self._device_path, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open {self._device_path}")

        # Configure capture
        fourcc = cv2.VideoWriter_fourcc(*self._pixel_format)
        self._cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

        # Query actual FPS
        self._actual_fps = self._cap.get(cv2.CAP_PROP_FPS)

        # Start capture thread
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self._running = True

    async def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap:
            self._cap.release()
            self._cap = None
        self._running = False

    def _read_loop(self) -> None:
        while not self._stop_event.is_set():
            ret, frame = self._cap.read()
            if not ret:
                self._queue.put(None)  # Signal device lost
                break

            self._frame_index += 1
            capture_frame = CaptureFrame(
                data=cv2.imencode('.jpg', frame)[1].tobytes(),
                timestamp_mono=time.monotonic(),
                timestamp_unix=time.time(),
                frame_index=self._frame_index,
                width=frame.shape[1],
                height=frame.shape[0]
            )

            try:
                self._queue.put_nowait(capture_frame)
            except Full:
                # Drop oldest frame (backpressure)
                try:
                    self._queue.get_nowait()
                except:
                    pass
                self._queue.put_nowait(capture_frame)

    async def __aiter__(self):
        return self

    async def __anext__(self) -> CaptureFrame:
        while self._running:
            try:
                frame = await asyncio.to_thread(self._queue.get, timeout=0.1)
                if frame is None:
                    raise StopAsyncIteration
                return frame
            except:
                if not self._running:
                    raise StopAsyncIteration
                continue
        raise StopAsyncIteration

    @property
    def actual_fps(self) -> float:
        return self._actual_fps

    @property
    def is_running(self) -> bool:
        return self._running
```

### Validation

- [ ] Opens camera at specified resolution/FPS
- [ ] Yields `CaptureFrame` objects
- [ ] Handles backpressure (drops old frames)
- [ ] `stop()` releases resources cleanly
- [ ] `actual_fps` property works

---

## P2.2: Frame Queue System

### Deliverables

Integrated into `capture.py` (P2.1).

### Design

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Capture      │     │ Queue        │     │ Async        │
│ Thread       │────►│ (size=3)     │────►│ Consumer     │
│ (blocking)   │     │ (bounded)    │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
```

### Backpressure Strategy

When queue is full:
1. Remove oldest frame from queue
2. Insert new frame
3. Log dropped frame (debug level)

This ensures:
- Consumer always gets recent frames
- No memory growth
- Producer never blocks indefinitely

### Validation

- [ ] Queue bounded to 3 frames
- [ ] Old frames dropped under backpressure
- [ ] No deadlocks under high load
- [ ] Queue depth queryable

---

## P2.3: Capture Loop Async

### Deliverables

| File | Contents |
|------|----------|
| `bridge.py` (partial) | `_capture_loop()` method |

### Implementation

```python
# In CamerasRuntime class (bridge.py)

async def _capture_loop(self) -> None:
    preview_interval = max(1, int(self._capture_fps / self._preview_fps))
    frame_count = 0

    async for frame in self._capture:
        frame_count += 1

        # Route to encoder if recording
        if self._recording and self._encoder:
            await self._encoder.push_frame(frame)

        # Route to preview at reduced rate
        if frame_count % preview_interval == 0:
            await self._push_preview(frame)

        # Update metrics periodically
        if frame_count % 5 == 0:
            self._update_metrics()

        # Check for stop signal
        if self._stop_capture.is_set():
            break
```

### Preview Frame Generation

```python
async def _push_preview(self, frame: CaptureFrame) -> None:
    if not self._view:
        return

    # Decode JPEG to RGB
    img = await asyncio.to_thread(
        cv2.imdecode,
        np.frombuffer(frame.data, np.uint8),
        cv2.IMREAD_COLOR
    )

    # Scale to canvas size
    canvas_w, canvas_h = self._view.canvas_size
    scale = min(canvas_w / frame.width, canvas_h / frame.height)
    new_w = int(frame.width * scale)
    new_h = int(frame.height * scale)
    img = cv2.resize(img, (new_w, new_h))

    # Convert BGR to RGB
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Create PPM data
    ppm = f"P6\n{new_w} {new_h}\n255\n".encode() + img.tobytes()

    # Push to view
    self._view.push_frame(ppm)
```

### Validation

- [ ] Frames routed to encoder when recording
- [ ] Preview updates at reduced rate
- [ ] Metrics updated every 5 frames
- [ ] Clean shutdown on stop signal
- [ ] No blocking calls in loop body
