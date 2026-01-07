# Architecture: Cameras-USB2

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     main_cameras.py                         │
│                    (Entry Point)                            │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                      bridge.py                              │
│                   CamerasRuntime                            │
│  ┌─────────────┬──────────────┬──────────────┐             │
│  │ assign_     │ start_       │ handle_      │             │
│  │ device()    │ recording()  │ command()    │             │
│  └─────────────┴──────────────┴──────────────┘             │
└────────┬────────────────┬─────────────────┬─────────────────┘
         │                │                 │
┌────────▼────────┐ ┌─────▼─────┐ ┌─────────▼─────────┐
│  camera_core/   │ │  storage/ │ │      app/         │
│  ├─capture.py   │ │  session_ │ │  ├─view.py        │
│  ├─capabilities │ │  paths.py │ │  └─widgets/       │
│  └─backends/    │ │           │ │    settings.py    │
│    usb_backend  │ │           │ │                   │
└─────────────────┘ └───────────┘ └───────────────────┘
```

## Data Flow

### Capture Pipeline

```
USB Camera
    │
    ▼ (V4L2/OpenCV)
┌──────────────┐
│ USBCapture   │  ← Background thread (dedicated), blocking read
│ _read_loop() │
└──────┬───────┘
       │ CaptureFrame (MJPG bytes + timestamps)
       ▼
┌──────────────┐
│ Frame Queue  │  ← queue.Queue, bounded size=3
│ (bounded)    │    Overflow: drop oldest (never blocks producer)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ _capture_    │  ← Async consumer (main thread)
│ loop()       │
└──────┬───────┘
       │
   ┌───┴───────────┐
   ▼               ▼
Preview         Encoder
(sync call)     (via asyncio.to_thread)
```

### Command Flow

```
Supervisor
    │
    │ handle_command(cmd, payload)
    ▼
┌──────────────┐
│ Cameras      │
│ Runtime      │
└──────┬───────┘
       │
       ├──► assign_device()
       ├──► start_recording()
       ├──► stop_recording()
       └──► apply_config()
```

## Component Responsibilities

### bridge.py - CamerasRuntime

| Method | Responsibility |
|--------|----------------|
| `__init__()` | Initialize state, create queues |
| `assign_device()` | Probe camera, cache capabilities, start capture |
| `unassign_device()` | Stop capture, release resources |
| `start_recording()` | Create encoder, open files, route frames |
| `stop_recording()` | Flush encoder, close files, report stats |
| `_capture_loop()` | Consume frames, route to preview/encoder |
| `handle_command()` | Dispatch commands to methods |

### camera_core/capture.py - USBCapture

| Method | Responsibility |
|--------|----------------|
| `__init__()` | Configure OpenCV VideoCapture |
| `start()` | Launch background read thread |
| `stop()` | Signal thread exit, join |
| `__aiter__()` | Yield frames from queue |
| `_read_loop()` | Blocking frame reads in thread |

### camera_core/backends/usb_backend.py

| Function | Responsibility |
|----------|----------------|
| `probe()` | Discover camera capabilities |
| `_probe_modes()` | Enumerate resolution/FPS combinations |
| `_probe_controls()` | Query adjustable controls |

### camera_core/capabilities.py

| Function | Responsibility |
|----------|----------------|
| `build_capabilities()` | Normalize raw probe data |
| `select_default_preview()` | Pick optimal preview mode |
| `select_default_record()` | Pick optimal record mode |

### storage/session_paths.py

| Function | Responsibility |
|----------|----------------|
| `resolve_session_paths()` | Build output file paths |

### app/view.py - CameraView

| Method | Responsibility |
|--------|----------------|
| `build_ui()` | Create Tkinter widgets |
| `push_frame()` | Update preview canvas |
| `update_metrics()` | Refresh metrics display |

## Key Types (from base module)

```python
CameraId        # Unique camera identifier
CameraDescriptor # Camera metadata (name, backend, device path)
CaptureFrame    # Frame data + timestamp
CameraCapabilities # Supported modes and controls
CapabilityMode  # Single resolution/FPS combination
```

## Threading Model

| Context | Purpose | Blocking? | Implementation |
|---------|---------|-----------|----------------|
| Main (asyncio) | Event loop, UI updates, orchestration | No | `asyncio.run()` |
| Capture thread | Frame reads from camera | Yes | `threading.Thread` (dedicated) |
| Encoder writes | Video file writes | Yes | `asyncio.to_thread()` (pooled) |

**Clarification**: Only the capture loop uses a dedicated thread because `cv2.VideoCapture.read()` blocks indefinitely. Encoder writes use `asyncio.to_thread()` which runs on the default thread pool executor - this is NOT a dedicated thread.

```
┌─────────────────────────────────────────────────────────┐
│                    Main Thread                          │
│                  (asyncio event loop)                   │
│                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │ _capture_   │    │ _encode_    │    │ UI updates  │ │
│  │ loop()      │    │ frame()     │    │ (Tkinter)   │ │
│  │ (async)     │    │ (async)     │    │             │ │
│  └──────┬──────┘    └──────┬──────┘    └─────────────┘ │
│         │                  │                            │
└─────────┼──────────────────┼────────────────────────────┘
          │                  │
          │ await            │ await asyncio.to_thread()
          │ queue.get()      │
          │                  ▼
┌─────────▼──────────┐  ┌─────────────────────┐
│  Capture Thread    │  │  ThreadPoolExecutor │
│  (dedicated)       │  │  (shared pool)      │
│                    │  │                     │
│  cv2.VideoCapture  │  │  encoder.write()    │
│  .read() [blocks]  │  │  [blocks briefly]   │
└────────────────────┘  └─────────────────────┘
```

## State Machine

```
              assign_device()
    IDLE ─────────────────────► CAPTURING
     ▲                              │
     │                              │ start_recording()
     │                              ▼
     │                          RECORDING
     │                              │
     │ unassign_device()            │ stop_recording()
     └──────────────────────────────┘
```
