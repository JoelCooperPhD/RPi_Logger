# Cameras_CSI Module

Raspberry Pi CSI camera module using Picamera2 with Elm/Redux architecture for state management.

## Supported Hardware

- **Raspberry Pi 5** with PiSP (Pi Signal Processor)
- **CSI cameras**: IMX296, IMX219, IMX477, IMX708, and other libcamera-supported sensors

## Architecture

Uses an Elm/Redux-style architecture with unidirectional data flow:

```
User Input → Action → Store.dispatch() → update() → new State + Effects
                                              ↓
                                    EffectExecutor (side effects)
                                              ↓
                                    View.render(state)
```

### Module Structure

```
Cameras_CSI/
├── main_cameras_csi.py   # Entry point (StubCodexSupervisor)
├── bridge.py             # CSICamerasRuntime (ModuleRuntime interface)
├── config.txt            # Module configuration
├── core/                 # Pure state machine
│   ├── state.py          # AppState, CameraStatus, RecordingStatus, CameraSettings
│   ├── actions.py        # Action types (AssignCamera, StartRecording, etc.)
│   ├── effects.py        # Effect types (OpenCamera, StartEncoder, etc.)
│   ├── update.py         # Pure reducer function
│   └── store.py          # Store class with subscribe/dispatch
├── capture/              # Camera frame capture
│   ├── picam_source.py   # PicamSource wrapping Picamera2
│   ├── frame.py          # CapturedFrame dataclass
│   ├── frame_buffer.py   # Async frame buffer with backpressure
│   └── source.py         # FrameSource protocol
├── recording/            # Video recording
│   ├── encoder.py        # VideoEncoder (OpenCV MJPG → AVI)
│   ├── timing_writer.py  # TimingCSVWriter for frame timestamps
│   └── session.py        # RecordingSession coordinator
├── infra/                # Side effect handlers
│   ├── effect_executor.py    # Executes effects (camera, encoder, preview)
│   └── command_handler.py    # JSON stdin/stdout command interface
├── ui/                   # User interface
│   ├── view.py           # CSICameraView (stub integration)
│   ├── renderer.py       # Standalone Tk renderer
│   └── widgets/
│       └── settings_window.py  # Camera settings dialog
└── tests/                # Test suite
```

## Capture Pipeline

Camera frames flow through:

1. **PicamSource**: Captures YUV420 frames from Picamera2 in a background thread
2. **FrameBuffer**: Thread-safe async buffer with overwrite-on-full semantics
3. **EffectExecutor**: Processes frames for preview and/or recording

### Frame Format

- **Sensor output**: YUV420 at native resolution (e.g., 1456x1088 for IMX296)
- **Buffer stride**: Padded for DMA alignment (e.g., 1456 → 1536 pixels)
- **Conversion**: YUV420 → BGR via OpenCV for recording/preview
- **Preview**: Software-scaled (default 1/4 scale) to PPM for Tkinter

## Recording

Recording uses OpenCV's VideoWriter with MJPG codec:

```
YUV420 frame → BGR conversion → VideoWriter → .avi file
           → TimingCSVWriter → _timing.csv file
```

### Output Files

Per-trial output in `<session_dir>/picam<N>/`:
- `trial_001.avi` - Video file (MJPG codec)
- `trial_001_timing.csv` - Frame timing data

### Timing CSV Format

```csv
trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,sensor_timestamp_ns,video_pts
```

## Configuration

Settings in `config.txt`:

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | false | Module enabled state |
| `preview_resolution` | auto | Preview resolution mode |
| `window_geometry` | 320x200 | Initial window size |

Runtime settings via Settings dialog:

| Setting | Default | Options |
|---------|---------|---------|
| Preview Scale | 1/4 | 1/2, 1/4, 1/8 |
| Preview FPS | 10 | 1, 2, 5, 10 |
| Record FPS | 5 | 1, 2, 5, 10, 15, 30 |

## Usage

### Standalone

```bash
python -m rpi_logger.modules.Cameras_CSI.main_cameras_csi --camera-index 0
```

### With Auto-Recording

```bash
python -m rpi_logger.modules.Cameras_CSI.main_cameras_csi \
    --camera-index 0 \
    --record \
    --output-dir /path/to/recordings
```

### CLI Arguments

| Argument | Description |
|----------|-------------|
| `--camera-index` | CSI camera index (0 or 1) |
| `--record` | Start recording immediately after camera assignment |
| `--output-dir` | Recording output directory |
| `--console-output` | Enable console logging |
| `--log-level` | Logging level (debug, info, warning, error) |

## Commands

JSON commands via stdin when running as subprocess:

| Command | Description |
|---------|-------------|
| `assign_device` | Assign camera by index or device_id (`picam:0`) |
| `unassign_device` | Release camera |
| `start_recording` | Start recording with session_dir and trial_number |
| `stop_recording` | Stop current recording |
| `shutdown` | Clean shutdown |

## State Machine

### Camera States

- `IDLE` - No camera assigned
- `ASSIGNING` - Probing camera
- `STREAMING` - Camera active, frames flowing
- `ERROR` - Camera error occurred

### Recording States

- `STOPPED` - Not recording
- `STARTING` - Encoder initializing
- `RECORDING` - Actively recording
- `STOPPING` - Finalizing recording

## Testing

```bash
pytest rpi_logger/modules/Cameras_CSI/tests/
```

Test categories:
- `tests/unit/` - Pure function tests (update, timing_writer)
- `tests/integration/` - Store and multi-component tests
- `tests/widget/` - UI component tests
