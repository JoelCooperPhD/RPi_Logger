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

> **Automatic camera detection:** The system automatically detects all connected cameras regardless of slot position or count. No configuration needed - just connect your cameras and start recording!

### Standalone Mode (Interactive)

```bash
# Start camera system with default settings (native resolution @ 30 FPS)
uv run main_camera.py

# HD 720p resolution at 25 FPS (preset 2)
uv run main_camera.py --resolution 2 --target-fps 25

# Custom output directory
uv run main_camera.py --output-dir recordings/my_session

# Low CPU mode: VGA recording (preset 5) with minimal preview (preset 7) at 10 FPS
uv run main_camera.py --resolution 5 --preview-size 7 --target-fps 10

# Interactive mode without preview (stdin command input: r/s/q + Enter)
uv run main_camera.py --no-preview

# Auto-start recording immediately on startup (good for unattended recording)
uv run main_camera.py --auto-start-recording

# Monitor logs in real-time (in another terminal)
tail -f recordings/session_*/session.log
```

### Slave Mode (Programmatic Control)

```bash
# Start in slave mode for master control (no preview by default in config)
uv run main_camera.py --mode slave --discovery-retry 3 --output-dir recordings/cameras

# Slave mode with local preview windows (alongside JSON commands)
uv run main_camera.py --mode slave --preview
```

### Master Control Example

> **Note**: An example master control program can be implemented by sending JSON commands to the slave process. See the "Programmatic Control" section below for implementation details.

## Usage Modes

### Standalone Mode Controls

**With Preview Window:**
- **`q`**: Quit application
- **`s`**: Take snapshot from all cameras
- **`r`**: Toggle recording on/off
- **Close Window**: Graceful shutdown

**Without Preview (`--no-preview`):**
Type single-letter commands followed by Enter:
- **`r`** + Enter: Toggle recording on/off
- **`s`** + Enter: Take snapshot from all cameras
- **`q`** + Enter: Quit application
- **Ctrl+C**: Also quits gracefully

### Slave Mode Commands

Send JSON commands via stdin when running in `--mode slave`:

```json
{"command": "start_recording"}
{"command": "stop_recording"}
{"command": "take_snapshot"}
{"command": "get_status"}
{"command": "toggle_preview", "camera_id": 0, "enabled": true}
{"command": "quit"}
```

**Command Responses:**
All commands return JSON status messages on stdout with format:
```json
{
  "type": "status",
  "status": "recording_started|recording_stopped|snapshot_taken|status_report|error|...",
  "timestamp": "ISO-8601 timestamp",
  "data": { /* command-specific data */ }
}
```

## Configuration

### Configuration File (config.txt)

The `config.txt` file allows you to set default values for system settings without passing CLI arguments. Settings include:

**Recording Settings:**
- `resolution_preset` - Recording resolution (0-7)
- `target_fps` - Recording frame rate
- `auto_start_recording` - Automatically start recording on startup (true/false)
- `disable_mp4_conversion` - Keep raw .h264 files for power-loss resilience (true/false)
- `output_dir`, `session_prefix` - Output configuration

**Display & Preview:**
- `show_preview` - Enable/disable preview windows (true/false)
- `preview_preset` - Preview window size (0-7)
- `show_frame_number` - Display frame numbers on video/preview
- `font_scale_base`, `thickness_base` - Text appearance
- `text_color_b/g/r` - Text color (BGR format)
- `margin_left`, `line_start_y` - Text position

**Advanced Settings:**
- `enable_csv_timing_log` - Enable/disable CSV diagnostic logging

**Logging Settings:**
- `log_level` - Python logging verbosity (debug, info, warning, error, critical)
- `console_output` - Also print logs to console (true/false, default: false)
- `libcamera_log_level` - libcamera/C library verbosity (DEBUG, INFO, WARN, ERROR, FATAL)
  - **WARN** (recommended): Only warnings and errors → clean logs
  - **INFO**: All messages → very verbose

> **Note**: CLI arguments always override config.txt values. Edit `config.txt` to change defaults.

> **Logging Behavior**: All output (including from C libraries like libcamera and Qt) is captured in `session.log`. ANSI color codes are automatically stripped for clean formatting. With `--console`, Python logging also writes to console, but C library messages remain file-only. Use `tail -f recordings/session_*/session.log` to monitor logs in real-time.

### CLI Arguments

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--resolution` | 0 (1456x1088) | Recording resolution preset (0-7). See config.txt for available presets |
| `--target-fps` | 30 | Recording frames per second (1-60 supported) |
| `--preview-size` | 7 (320x240) | Preview window size preset (0-7). Smaller = lower CPU usage |
| `--output-dir` | `recordings` | Output directory for session folders |
| `--mode` | interactive | Execution mode (`interactive`, `headless`, `slave`) |
| `--session-prefix` | session | Prefix for generated session folders |
| `--auto-start-recording` | False | Automatically start recording on startup |
| `--no-auto-start-recording` | - | Wait for manual recording command (default) |
| `--preview` | True | Show preview window (enabled by default) |
| `--no-preview` | - | Disable preview window (headless operation) |
| `--console` | False | Also log to console (in addition to file) |
| `--no-console` | - | Log to file only (no console output, default) |
| `--libcamera-log-level` | WARN | libcamera verbosity (DEBUG/INFO/WARN/ERROR/FATAL) |

**Resolution Presets (0-7) for IMX296 camera:**
- 0: 1456x1088 - Native (Full sensor, no scaling) - 4:3
- 1: 1280x960 - SXGA (Slight downscale) - 4:3
- 2: 1280x720 - HD 720p (Standard HD) - 16:9
- 3: 1024x768 - XGA (Good balance) - 4:3
- 4: 800x600 - SVGA (Lower CPU) - 4:3
- 5: 640x480 - VGA (Minimal CPU) - 4:3
- 6: 480x360 - QVGA+ (Very low CPU) - 4:3
- 7: 320x240 - QVGA (Ultra minimal) - 4:3

> **Note**: Most settings can also be configured in `config.txt` to avoid passing CLI arguments. CLI arguments override config file values.

## File Structure

```
Cameras/
├── main_camera.py                   # Main multi-camera system entry point
├── README.md                        # This documentation
├── config.txt                       # System configuration (resolution, FPS, overlay settings)
├── camera_core/                     # Core camera system modules
│   ├── camera_capture_loop.py      # Async capture at hardware FPS (1-60)
│   ├── camera_processor.py         # Processing orchestrator (polls capture directly)
│   ├── camera_overlay.py           # Overlay rendering
│   ├── camera_display.py           # Display management
│   ├── camera_handler.py           # Single camera coordinator
│   ├── camera_system.py            # Multi-camera system with interactive/slave/headless modes
│   ├── camera_supervisor.py        # Async supervisor with retry logic
│   ├── camera_utils.py             # Utilities (FPS tracker, config loader, metadata)
│   ├── recording/                  # Recording subsystem (modular design)
│   │   ├── manager.py              # Recording coordinator (public API)
│   │   ├── encoder.py              # H.264 hardware encoder wrapper
│   │   ├── overlay.py              # Frame overlay handler
│   │   ├── csv_logger.py           # CSV timing logger (threaded)
│   │   ├── remux.py                # Video format conversion utilities
│   │   └── __init__.py             # Recording module exports
│   ├── commands/                   # JSON command protocol
│   │   ├── command_handler.py      # Command processing
│   │   ├── command_protocol.py     # Command definitions
│   │   └── __init__.py             # Command exports
│   ├── config/                     # Configuration management
│   │   ├── config_loader.py        # Config file loading
│   │   ├── camera_config.py        # Camera configuration utilities
│   │   └── __init__.py             # Config exports
│   ├── modes/                      # Operation modes
│   │   ├── base_mode.py            # Base mode class
│   │   ├── interactive_mode.py     # Interactive mode with preview
│   │   ├── slave_mode.py           # JSON command-driven mode
│   │   ├── headless_mode.py        # Background recording mode
│   │   └── __init__.py             # Mode exports
│   └── __init__.py                 # Package exports
└── docs/                            # Technical documentation
    ├── camera_module_spec.md        # Camera hardware specifications
    └── picamera2_reference.md       # Picamera2 API reference
```

## Session Output

Each runtime spawns a dedicated session folder inside the configured `--output-dir` directory:

**Directory Structure:**
```
recordings/
└── session_YYYYMMDD_HHMMSS/
    ├── session.log                              # System log file
    ├── cam0_1456x1088_30.0fps_TIMESTAMP.mp4   # Camera 0 recording
    ├── cam0_1456x1088_30.0fps_TIMESTAMP_frame_timing.csv  # Frame timing data
    ├── cam1_1456x1088_30.0fps_TIMESTAMP.mp4   # Camera 1 recording
    ├── cam1_1456x1088_30.0fps_TIMESTAMP_frame_timing.csv
    └── snapshot_cam0_TIMESTAMP.jpg             # Snapshots
```

**Log File:**
- `session.log` — Complete system log for the session
  - **All output captured:** Python logging + C library output (libcamera, Qt, OpenCV)
  - All camera system events, errors, and status messages
  - Paired with recordings for easy troubleshooting
  - Log level configurable via `log_level` in config.txt or `--log-level` CLI argument
  - Console output disabled by default (logs to file only)
  - Use `tail -f session.log` to monitor logs in real-time

**Video Files:**
- `cam{N}_WIDTHxHEIGHT_FPSfps_TIMESTAMP.h264` — Raw H.264 hardware-encoded video (default)
  - Better for unattended recording (power-loss resilient)
  - Playable in VLC and most modern players
  - Frame numbers burned into video via hardware overlay
- `cam{N}_WIDTHxHEIGHT_FPSfps_TIMESTAMP.mp4` — MP4 container format (optional)
  - Enable by setting `disable_mp4_conversion = false` in config.txt
  - Adds framerate metadata for better compatibility
  - Requires graceful shutdown (not power-loss safe)

**Diagnostic CSV:**
- `cam{N}_WIDTHxHEIGHT_FPSfps_TIMESTAMP_frame_timing.csv` — per-frame timing diagnostics
  - **Columns:** `frame_number`, `write_time_unix`, `sensor_timestamp_ns`, `dropped_since_last`, `total_hardware_drops`
  - Enables precise frame-by-frame analysis and dropped frame detection
  - Optional (disable with `enable_csv_timing_log = false` in config.txt for better performance)

**Snapshots:**
- `snapshot_cam{N}_TIMESTAMP.jpg` — JPEG snapshots captured on-demand
  - Saved in same session folder as videos
  - Can be triggered via 's' key (interactive mode) or `take_snapshot` command (slave mode)

## Architecture

### System Overview

The camera system uses a **simplified 2-loop async architecture** for optimal performance:

```
Camera Hardware (configurable 1-60 FPS)
    ↓
Capture Loop → extracts hardware_fps from metadata
    ↓
Processor Loop (polls capture directly) → orchestrates processing pipeline
    ├→ Overlay Renderer → adds text, FPS, counters
    ├→ Display Manager → thread-safe preview frames
    └→ Recording Module → modular recording subsystem
        ├→ H.264 Encoder → hardware-accelerated encoding
        ├→ CSV Logger → frame timing diagnostics (threaded)
        ├→ Overlay Handler → frame number overlay via post_callback
        └→ Remuxer → H.264 to MP4 conversion
```

**Key Features:**
- **Flexible FPS**: Supports 1-60 FPS at hardware level (IMX296 sensor max: 60 FPS @ 1456x1088)
- **Simplified Architecture**: 2 async loops (capture → processor) with direct polling
- **Metadata Propagation**: Hardware FPS flows from camera → capture → processor → overlay
- **Zero Frame Drops**: Optimized capture pipeline with atomic frame+metadata retrieval via `capture_request()`
- **Hardware Drop Detection**: Uses sensor timestamp deltas to accurately detect dropped frames
- **Dual-Stream Architecture**: Lores stream for preview (hardware-scaled), main stream for H.264 recording
- **Modular Recording**: Recording subsystem split into focused components (encoder, CSV logger, overlay, remux)

### Standalone Mode (Interactive)
- **With Preview** (default):
  - Multiple OpenCV preview windows (one per camera)
  - Real-time FPS display showing collation and hardware FPS
  - Frame counters showing collated and captured frame totals
  - Interactive keyboard controls (q/r/s)
  - Direct camera control
- **Without Preview** (`--no-preview`):
  - Runs without GUI windows (stdin command input)
  - Single-letter commands via stdin: r (record), s (snapshot), q (quit)
  - Lower CPU usage (no window rendering)
  - Keeps camera pipeline active

### Slave Mode
- **Without Preview** (default):
  - No GUI interface (pure headless operation)
  - JSON command protocol via stdin/stdout
  - Real-time status reporting to master process
- **With Preview** (`--preview`):
  - Shows local OpenCV windows alongside JSON commands
  - Useful for debugging or monitoring slave processes
- **Frame Streaming** (optional):
  - Base64-encoded JPEG frames via JSON (@ ~30 FPS)
  - Toggle per-camera with `toggle_preview` command
  - Frames sent as `preview_frame` status messages
- Signal handling for graceful shutdown (SIGTERM, SIGINT)

### Headless Mode
- Continuous recording without preview (auto-starts)
- Minimal CPU overhead
- Suitable for long-running background recording
- Can be combined with `--preview` for monitoring

## Performance Characteristics

- **Hardware-Accelerated Encoding**: H.264 encoding via GPU with automatic .h264 to .mp4 conversion
  - Minimal CPU usage for video encoding
  - Main stream: Full resolution recording via hardware encoder
  - Lores stream: Hardware-scaled preview (no CPU scaling required)
- **Accurate Frame Timing**: Hardware sensor timestamps enable nanosecond-precision drop detection
  - Dropped frames detected via `SensorTimestamp` delta analysis
  - Cumulative drop counters tracked per recording
- **Frame Number Correlation**: Burned-in frame numbers correlate video frames with CSV diagnostic data
  - Recording: Overlay added via `post_callback` at camera level (hardware efficient)
  - Preview: Overlay added in processor (identical appearance)
- **Low Latency**: <1 ms control-path latency for commands in both interactive and slave modes
- **Zero-Copy Pipeline**: Direct frame buffer access via `MappedArray` (no frame copies for overlay rendering)
- **Comprehensive Diagnostics**: Per-recording CSV logs enable offline frame-by-frame analysis
  - Frame numbers, Unix timestamps, sensor timestamps (nanoseconds)
  - Per-frame and cumulative drop counts

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
# Start interactive mode with HD 720p resolution (preset 2)
uv run main_camera.py --resolution 2

# Controls:
# Press 'r' to start/stop recording
# Press 's' to take snapshots
# Press 'q' to quit
```

### Programmatic Control

```python
import subprocess
import json
import time

# Start camera system in slave mode
proc = subprocess.Popen(
    ["uv", "run", "main_camera.py", "--mode", "slave"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1  # Line buffered
)

# Wait for initialization
time.sleep(2)

# Send start recording command
proc.stdin.write(json.dumps({"command": "start_recording"}) + "\n")
proc.stdin.flush()

# Read status response
status = json.loads(proc.stdout.readline())
print(f"Recording started: {status}")

# Record for 10 seconds
time.sleep(10)

# Stop recording
proc.stdin.write(json.dumps({"command": "stop_recording"}) + "\n")
proc.stdin.flush()
status = json.loads(proc.stdout.readline())
print(f"Recording stopped: {status}")

# Get status
proc.stdin.write(json.dumps({"command": "get_status"}) + "\n")
proc.stdin.flush()
status = json.loads(proc.stdout.readline())
print(f"System status: {status}")

# Cleanup
proc.stdin.write(json.dumps({"command": "quit"}) + "\n")
proc.stdin.flush()
proc.wait()
```

## Support

For issues and questions, refer to the main project documentation in `/CLAUDE.md`.
