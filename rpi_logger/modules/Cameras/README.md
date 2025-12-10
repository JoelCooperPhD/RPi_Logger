# Cameras Module

Single-camera-per-instance module for USB and Pi CSI cameras.

## Architecture

Each Cameras module instance handles exactly **one camera**. The camera ID is
passed to the module at launch via the `assign_device` command from the main
logger's DeviceSystem.

### Key Design Points

- **No discovery**: Camera discovery is handled by the main logger (`usb_camera_scanner.py`, `csi_scanner.py`). This module only receives pre-identified camera assignments.
- **In-process capture**: Camera capture runs directly in the module process using async I/O.
- **Model-based caching**: Known camera models (e.g., "C920", "imx296") have their capabilities cached in `camera_models.json` to skip probing on subsequent launches.
- **Dual pipelines**: Preview (low-res, UI-facing) and record (full-quality) streams run concurrently.

## Data Flow

```
Main Logger DeviceSystem
         |
         | assign_device command
         v
+--------------------+
|   CamerasRuntime   |
|   (bridge.py)      |
+--------+-----------+
         |
         | Check CameraModelDatabase
         | (skip probe if known model)
         v
+--------------------+
|   camera_core/     |
|   capture, encode  |
+--------------------+
```

## Structure

```
Cameras/
├── bridge.py                 # Main runtime, handles commands
├── camera_models.py          # Model database for capability caching
├── config.py                 # Typed configuration
├── utils.py                  # Parsing utilities
│
├── app/                      # UI components
│   ├── view.py               # View adapter
│   └── widgets/              # Camera settings window
│
├── camera_core/              # Core capture functionality
│   ├── state.py              # State dataclasses (CameraId, etc.)
│   ├── capture.py            # PicamCapture, USBCapture
│   ├── encoder.py            # Video encoding
│   ├── preview.py            # Preview frame conversion
│   ├── capabilities.py       # Capability building
│   └── backends/             # picam_backend, usb_backend
│
└── storage/
    ├── camera_models.json    # Cached camera capabilities by model
    ├── known_cameras.json    # Per-instance settings cache
    ├── disk_guard.py         # Free space checks
    ├── known_cameras.py      # Settings cache implementation
    └── session_paths.py      # Recording path generation
```

## Commands

| Command | Description |
|---------|-------------|
| `assign_device` | Assign a camera to this module instance |
| `unassign_device` | Remove camera assignment |
| `start_recording` | Begin recording on assigned camera |
| `stop_recording` | Stop recording |
| `start_session` | Update session directory |
| `stop_session` | End current session |

## Configuration

### Model Database (`camera_models.json`)

Capabilities are cached by hardware model name (e.g., "Logitech C920", "imx296").
When a known model is connected, probing is skipped and cached capabilities are used.
New cameras are probed once, then added to the database for future launches.

### Per-Instance Settings (`known_cameras.json`)

User settings are cached per camera instance (by port/path):
- `preview_resolution`, `preview_fps`
- `record_resolution`, `record_fps`
- `overlay` (timestamp overlay)
