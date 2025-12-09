# Cameras Module

Single-camera-per-instance module for USB and Pi CSI cameras.

## Architecture

Each Cameras module instance handles exactly **one camera**. The camera ID is
passed to the module at launch via the `assign_device` command from the main
logger's DeviceSystem.

### Key Design Points

- **No discovery**: Camera discovery is handled by the main logger (`usb_camera_scanner.py`, `csi_scanner.py`). This module only receives pre-identified camera assignments.
- **Worker subprocess**: Each camera runs in its own subprocess with an independent GIL for optimal recording performance.
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
         v
+------------------------+
| WorkerSpawnController  |
| (bridge_controllers.py)|
+--------+---------------+
         |
         v
+--------------------+
|   WorkerManager    |
| (coordinator/)     |
+--------+-----------+
         |
         v
+--------------------+
|  Camera subprocess |
|  (worker/)         |
+--------------------+
```

## Structure

```
Cameras/
├── bridge.py                 # Main runtime, handles commands
├── bridge_controllers.py     # WorkerSpawnController, RecordingController
├── config.py                 # Typed configuration
├── defaults.py               # Default values
├── main_cameras.py           # Entry point
├── utils.py                  # Parsing utilities
│
├── app/                      # UI components
│   ├── view.py               # View adapter
│   └── widgets/              # Camera tab, settings panel
│
├── runtime/
│   ├── state.py              # State dataclasses (CameraId, etc.)
│   ├── backends/             # picam_backend, usb_backend
│   ├── coordinator/          # WorkerManager, PreviewReceiver
│   └── discovery/            # Capability probing utilities
│
├── storage/
│   ├── disk_guard.py         # Free space checks
│   ├── known_cameras.py      # Per-camera settings cache
│   ├── session_paths.py      # Recording path generation
│   └── retention.py          # Session cleanup
│
└── worker/                   # Subprocess implementation
    ├── main.py               # CameraWorker entry
    ├── capture.py            # Frame capture
    ├── encoder.py            # Video encoding
    ├── preview.py            # Preview streaming
    └── protocol.py           # IPC messages
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

Per-camera settings are cached in `storage/known_cameras.json` and include:
- `preview_resolution`, `preview_fps`
- `record_resolution`, `record_fps`
- `overlay` (timestamp overlay)
