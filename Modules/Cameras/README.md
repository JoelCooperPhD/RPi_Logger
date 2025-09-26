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

### Standalone Mode (Interactive)

```bash
# Start camera system with default settings
uv run camera_module.py

# Custom resolution and frame rate
uv run camera_module.py --width 1280 --height 720 --fps 25

# Custom output directory
uv run camera_module.py --output recordings
```

### Slave Mode (Programmatic Control)

```bash
# Start in slave mode for master control
uv run camera_module.py --slave --output recordings
```

### Master Control Example

```bash
# Run example master program
uv run camera_master.py
```

## Usage Modes

### Standalone Mode Controls

- **`q`**: Quit application
- **`s`**: Take snapshot from all cameras
- **`r`**: Toggle recording on/off
- **Close Window**: Graceful shutdown

### Slave Mode Commands

Send JSON commands via stdin when running in `--slave` mode:

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
| `--width` | 1920 | Recording width in pixels |
| `--height` | 1080 | Recording height in pixels |
| `--fps` | 30 | Frames per second |
| `--preview-width` | 640 | Preview window width |
| `--preview-height` | 360 | Preview window height |
| `--output` | "recordings" | Output directory for files |
| `--slave` | False | Run in slave mode (no GUI) |

## File Structure

```
Cameras/
├── camera_module.py          # Main multi-camera system
├── camera_master.py          # Example master control program
├── README.md                 # This documentation
└── picamera2_reference.md    # Technical reference
```

## Session Output

Each runtime spawns a dedicated session folder inside the configured `--output` directory:

- `session_YYYYMMDD_HHMMSS/` — container for all recordings captured during the run
- `cam{N}_WIDTHxHEIGHT_FPSfps_TIMESTAMP.mp4` — H.264 scene recording per camera
- `cam{N}_WIDTHxHEIGHT_FPSfps_TIMESTAMP_frame_timing.csv` — per-frame diagnostics (expected cadence, queue latency, capture timestamps, drop/duplicate counters)

Snapshots (`snapshot_cam{N}_TIMESTAMP.jpg`) continue to save alongside the video artefacts in the same session folder.

## Architecture

### Standalone Mode
- Multiple OpenCV preview windows (one per camera)
- Real-time FPS display and timestamps
- Interactive keyboard controls
- Direct camera control

### Slave Mode
- No GUI interface
- JSON command protocol via stdin/stdout
- Status reporting to master process
- Signal handling for graceful shutdown

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

1. **Camera Busy Error**: Kill existing processes with `pkill -f camera_module`
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
uv run camera_module.py --width 1280 --height 720

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
    ["uv", "run", "camera_module.py", "--slave"],
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
