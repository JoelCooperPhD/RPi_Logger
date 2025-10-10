# Camera Module

A professional multi-camera recording system for Raspberry Pi 5 with master-slave architecture, real-time preview, and programmatic control.

## Features

🎥 **Multi-Camera Support**: Simultaneous recording from multiple cameras (tested with 2x IMX296)
📹 **High-Quality Recording**: H.264 video encoding with configurable resolution and frame rate
🧭 **Precise Frame Timing**: Deterministic FPS enforcement with dropped/duplicate tracking and per-recording diagnostics
⏰ **Timestamp Overlays**: Automatic timestamp and FPS embedding in preview
🔄 **Master-Slave Architecture**: Command-driven operation via JSON protocol
🖱️ **Interactive Controls**: Standalone mode with keyboard shortcuts (q=quit, s=snapshot, r=record)
⚙️ **Flexible Configuration**: Multiple resolutions, frame rates, and output options
📸 **Synchronized Snapshots**: Simultaneous image capture from both cameras
🛡️ **Signal Handling**: Graceful shutdown with proper resource cleanup

## Hardware Requirements

- **Raspberry Pi 5** (recommended for multi-camera support)
- **Multiple Camera Modules** (tested with 2x IMX296 Global Shutter sensors)
- **Adequate Cooling** (multi-camera operation generates heat)
- **Fast Storage** (Class 10+ SD card or USB 3.0 storage)
- **Operating System**: Raspberry Pi OS Bullseye or later

## Quick Start

> **Hot-plug friendly:** the controller stays alive when no cameras are present and retries discovery every `--discovery-retry` seconds so you can connect hardware without restarting.

### Standalone Mode (Interactive)

```bash
# Start camera system with default settings
uv run main_camera.py

# Custom resolution and frame rate
uv run main_camera.py --resolution 1280x720 --target-fps 25

# Custom output directory
uv run main_camera.py --output-dir recordings/cameras
```

### Slave Mode (Programmatic Control)

```bash
# Start in slave mode for master control
uv run main_camera.py --mode slave --discovery-retry 3 --output-dir recordings/cameras
```

### Master Control Example

```bash
# Run example master program
uv run examples/camera_master.py
```

## Usage Modes

### Standalone Mode Controls

- **`q`**: Quit application
- **`s`**: Take snapshot from all cameras
- **`r`**: Toggle recording on/off
- **Close Window**: Graceful shutdown

### Slave Mode Commands

Send JSON commands via stdin when running in `--mode slave`:

```json
{"command": "start_recording"}
{"command": "stop_recording"}
{"command": "take_snapshot"}
{"command": "get_status"}
{"command": "quit"}
```

## Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--resolution` | 1920x1080 | Recording resolution as WIDTHxHEIGHT |
| `--target-fps` | 30 | Recording frames per second |
| `--preview-size` | 640x360 | Preview window size as WIDTHxHEIGHT |
| `--output-dir` | `recordings/cameras` | Output directory for session folders |
| `--mode` | interactive | Execution mode (`interactive`, `headless`, `slave`) |
| `--discovery-timeout` | 5 | Seconds to wait for camera discovery |
| `--discovery-retry` | 3 | Seconds between discovery retries when no devices are found |
| `--min-cameras` | 2 | Minimum cameras required before starting |
| `--allow-partial` | False | Allow running with fewer cameras than minimum |
| `--session-prefix` | session | Prefix for generated session folders |

## File Structure

```
Cameras/
├── main_camera.py            # Main multi-camera system entry point
├── README.md                 # This documentation
├── config.txt                # Overlay configuration (JSON)
├── camera_core/              # Core camera system modules
│   ├── camera_capture_loop.py    # Async capture at 30 FPS
│   ├── camera_collator_loop.py   # Timing-based collation
│   ├── camera_processor.py       # Processing orchestrator
│   ├── camera_overlay.py         # Overlay rendering
│   ├── camera_display.py         # Display management
│   ├── camera_recorder.py        # Video recording
│   ├── camera_handler.py         # Single camera coordinator
│   ├── camera_system.py          # Multi-camera system
│   ├── camera_supervisor.py      # Retry wrapper
│   ├── camera_utils.py           # Utilities
│   ├── __init__.py               # Package exports
│   └── README.md                 # Core module documentation
├── examples/                 # Example scripts and demos
│   ├── camera_master.py      # Example master control program
│   └── simple_camera_test*.py # Simple test scripts
└── docs/                     # Technical documentation
    └── architecture.md       # System architecture details
```

## Session Output

Each runtime spawns a dedicated session folder inside the configured `--output` directory:

- `session_YYYYMMDD_HHMMSS/` — container for all recordings captured during the run
- `cam{N}_WIDTHxHEIGHT_FPSfps_TIMESTAMP.mp4` — H.264 scene recording per camera
- `cam{N}_WIDTHxHEIGHT_FPSfps_TIMESTAMP_frame_timing.csv` — per-frame diagnostics (expected cadence, queue latency, capture timestamps, drop/duplicate counters)

Snapshots (`snapshot_cam{N}_TIMESTAMP.jpg`) continue to save alongside the video artefacts in the same session folder.

## Architecture

### System Overview

The camera system uses a **3-loop async architecture** for optimal performance:

```
Camera Hardware (30 FPS)
    ↓
Capture Loop (30 FPS) → extracts hardware_fps from metadata
    ↓
Collator Loop (10 FPS) → timing-based frame collation
    ↓
Processor Loop → orchestrates processing pipeline
    ├→ Overlay Renderer → adds text, FPS, counters
    ├→ Display Manager → thread-safe preview frames
    └→ Recording Manager → ffmpeg encoding + timing CSV
```

**Key Features:**
- **Hardware FPS Decoupling**: Camera captures at 30 FPS, display/recording at 10 FPS
- **Independent Async Loops**: Capture, collator, and processor run concurrently
- **Metadata Propagation**: Hardware FPS flows from camera → capture → collator → processor → overlay
- **Frame Management**: Automatic duplication/skipping based on FPS mismatch

### Standalone Mode
- Multiple OpenCV preview windows (one per camera)
- Real-time FPS display: `FPS_10: 10 / 30` (collation / hardware)
- Frame counters: `Frames: 100 / 300` (collated / captured)
- Interactive keyboard controls
- Direct camera control

### Slave Mode
- No GUI interface
- JSON command protocol via stdin/stdout
- Status reporting to master process
- Signal handling for graceful shutdown
- Optional base64-encoded frame streaming for remote preview

### Headless Mode
- Continuous recording without preview
- Minimal CPU overhead
- Suitable for long-running background recording

## Performance Characteristics

- **Deterministic Output FPS**: Timer-driven recorder guarantees the requested cadence (1 / `--fps`) for every saved frame
- **Real-Time Telemetry**: Preview overlay surfaces sensor FPS, dropped/duplicate counters, and recorded frame totals
- **Comprehensive Diagnostics**: Per-recording CSV exposes queue latency, capture-to-write timing, and cadence error for offline analysis
- **Command Response**: <1 ms control-path latency retained in both preview and slave modes

## Dependencies

- **picamera2**: Camera control and capture
- **opencv-python**: Image processing and display
- **numpy**: Array operations

All dependencies are managed via `uv` package manager.

## Troubleshooting

### Common Issues

1. **Camera Busy Error**: Kill existing processes with `pkill -f main_camera`
2. **Import Errors**: Use `uv run` instead of direct Python execution
3. **Permission Issues**: Ensure user is in camera/video groups
4. **Resource Conflicts**: Only one instance can access cameras at a time

### Hardware Setup

1. Connect cameras to Pi 5 CSI ports (tested with 2x IMX296)
2. Ensure adequate cooling (multiple cameras generate heat)
3. Use fast storage for recording (USB 3.0 recommended)
4. Verify camera detection: `libcamera-hello --list-cameras`

## Examples

### Basic Recording Session

```bash
# Start interactive mode
uv run main_camera.py --width 1280 --height 720

# Controls:
# Press 'r' to start recording
# Press 's' to take snapshots
# Press 'q' to quit
```

### Programmatic Control

```python
import subprocess
import json

# Start camera system
proc = subprocess.Popen(
    ["uv", "run", "main_camera.py", "--slave"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True
)

# Send commands
proc.stdin.write(json.dumps({"command": "start_recording"}) + "\n")
proc.stdin.flush()

# Read status
status = json.loads(proc.stdout.readline())
print(f"Status: {status}")

# Cleanup
proc.stdin.write(json.dumps({"command": "quit"}) + "\n")
proc.wait()
```

## Support

For issues and questions, refer to the main project documentation in `/CLAUDE.md`.
