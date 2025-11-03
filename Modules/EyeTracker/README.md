# Eye Tracker Module

A professional eye tracking system for Raspberry Pi with Pupil Labs integration, real-time gaze overlay, CSV data export, and flexible control modes.

## Features

👁️ **Pupil Labs Integration**: Seamless integration with Pupil Labs eye trackers (Invisible/Neon)
📹 **Gaze Recording**: High-quality gaze data with scene video recording
🎯 **Real-Time Preview**: OpenCV-based preview with gaze overlay in interactive mode
⏰ **Multi-Stream Capture**: Synchronized gaze, IMU, events, and video data
🎧 **Optional Audio Capture**: Headset microphone stream saved to WAV with timing metadata
📈 **Device Telemetry Logging**: Periodic battery, storage, and sensor status snapshots
🔄 **Multiple Modes**: Standalone (interactive), headless, and slave (master logger) modes
🖱️ **Interactive Controls**: Keyboard shortcuts in standalone mode (q=quit, r=record)
⚙️ **Flexible Configuration**: Configurable resolution (up to 1920x1080), processing FPS (1-120)
🛡️ **Signal Handling**: Graceful shutdown with proper resource cleanup
📊 **CSV Export**: All data streams exported to CSV format for analysis

## Hardware Requirements

- **Raspberry Pi 5** (or compatible Raspberry Pi models)
- **Pupil Labs Eye Tracker** (tested with Pupil Invisible/Neon)
- **Network Connection** (for device discovery via RTSP)
- **Fast Storage** (Class 10+ SD card or USB 3.0 storage recommended)
- **Operating System**: Raspberry Pi OS Bullseye or later

## Quick Start

> **Automatic device discovery:** The system automatically discovers Pupil Labs eye tracker devices on the network. No manual configuration needed!

### Standalone Mode (Interactive)

```bash
# Start eye tracker system with default settings (5 FPS)
uv run main_tracker.py

# Higher quality tracking (30 FPS)
uv run main_tracker.py --target-fps 30

# Custom output directory
uv run main_tracker.py --output-dir recordings/my_session

# Full HD resolution
uv run main_tracker.py --resolution 1920x1080 --target-fps 10

# Auto-start recording immediately on startup
uv run main_tracker.py --auto-start-recording

# Monitor logs in real-time (in another terminal)
tail -f recordings/tracking_*/session.log
```

### Slave Mode (Master Logger Control)

```bash
# Typically launched automatically by main logger, but can be tested manually:
uv run main_tracker.py --mode headless --output-dir data/session_test/EyeTracker
```

### Integration with Main Logger

The eye tracker module is typically used via the master logger (`main_logger.py`), which:
- Automatically launches the module in headless/slave mode
- Sends JSON commands for session/recording control
- Receives status updates and handles module lifecycle
- Coordinates synchronization across all modules

## Usage Modes

### Interactive Mode Controls

**With OpenCV Preview Window:**
- **`q`**: Quit application
- **`r`**: Toggle recording on/off
- **Close Window**: Graceful shutdown

### Slave Mode Commands

Send JSON commands via stdin when running in `--mode slave`:

```json
{"command": "start_recording"}
{"command": "stop_recording"}
{"command": "get_status"}
{"command": "quit"}
```

**Command Responses:**
All commands return JSON status messages on stdout with format:
```json
{
  "type": "status",
  "status": "recording_started|recording_stopped|status_report|error|...",
  "timestamp": "ISO-8601 timestamp",
  "data": { /* command-specific data */ }
}
```

## Configuration

### Configuration File (config.txt)

The `config.txt` file allows you to set default values for system settings without passing CLI arguments. Settings include:

**Recording Settings:**
- `target_fps` - Processing frame rate (1-120 fps, recommended: 5-30)
- `resolution_width`, `resolution_height` - Scene video resolution
- `auto_start_recording` - Automatically start recording on startup (true/false)
- `output_dir`, `session_prefix` - Output configuration

**Data Export:**
- `enable_advanced_gaze_logging` - Write extended gaze CSV with per-eye metrics
- `expand_eye_event_details` - Include fixation/saccade metrics in EVENTS CSV
- `enable_audio_recording` - Capture headset microphone audio to WAV/CSV
- `audio_stream_param` - RTSP query string used to locate the audio stream
- `enable_device_status_logging` - Periodically log battery/memory/sensor status
- `device_status_poll_interval` - Seconds between telemetry samples while recording

**Display & Preview:**
- `preview_width` - Preview window width in pixels

**Logging Settings:**
- `log_level` - Python logging verbosity (debug, info, warning, error, critical)
- `console_output` - Also print logs to console (true/false, default: false)

**Advanced Settings:**
- `discovery_timeout` - Device discovery timeout (seconds)
- `discovery_retry` - Retry interval after failure (seconds)

> **Note**: CLI arguments always override config.txt values. Edit `config.txt` to change defaults.

> **Logging Behavior**: All output is captured in `session.log`. ANSI color codes are automatically stripped for clean formatting. With `--console`, Python logging also writes to console. Use `tail -f recordings/tracking_*/session.log` to monitor logs in real-time.

### CLI Arguments

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--target-fps` | 5.0 | Processing frame rate (1-120) |
| `--resolution` | 1280x720 | Scene video resolution (WIDTHxHEIGHT) |
| `--preview-width` | 640 | Preview window width in pixels |
| `--output-dir` | `recordings` | Output directory for session folders |
| `--mode` | headless | Execution mode (`interactive`, `headless`, `slave`) |
| `--session-prefix` | tracking | Prefix for generated session folders |
| `--auto-start-recording` | False | Automatically start recording on startup |
| `--no-auto-start-recording` | - | Wait for manual recording command (default) |
| `--console` | False | Also log to console (in addition to file) |
| `--no-console` | - | Log to file only (no console output, default) |
| `--log-level` | info | Python logging verbosity (debug/info/warning/error/critical) |
| `--discovery-timeout` | 5.0 | Device discovery timeout (seconds) |
| `--discovery-retry` | 3.0 | Retry interval after device failure (seconds) |
| `--advanced-gaze-logging` | config | Enable extended gaze CSV (use `--no-advanced-gaze-logging` to disable) |
| `--enable-eye-event-details` | config | Include fixation/saccade metrics in EVENTS CSV (`--disable-eye-event-details` disables) |
| `--enable-audio-recording` | config | Capture headset audio stream (`--disable-audio-recording` disables) |
| `--audio-stream-param` | `audio=scene` | RTSP query parameter used to locate audio stream |
| `--log-device-status` | config | Record periodic device telemetry (`--no-log-device-status` disables) |
| `--device-status-interval` | 5.0 | Poll interval (seconds) for telemetry logging |

> **Note**: Most settings can also be configured in `config.txt` to avoid passing CLI arguments. CLI arguments override config file values.

## File Structure

```
EyeTracker/
├── main_tracker.py                   # Main eye tracker system entry point
├── README.md                         # This documentation
├── config.txt                        # System configuration (FPS, resolution, logging settings)
├── tracker_core/                     # Core tracker system modules
│   ├── device_manager.py             # Pupil Labs device discovery and connection
│   ├── stream_handler.py             # RTSP stream handling (video, gaze, IMU, events)
│   ├── frame_processor.py            # Frame processing and OpenCV display
│   ├── gaze_tracker.py               # Main tracking orchestrator
│   ├── tracker_system.py             # System coordinator with interactive/slave/headless modes
│   ├── tracker_supervisor.py         # Async supervisor with retry logic
│   ├── tracker_utils.py              # Utilities (FPS tracker, helpers)
│   ├── constants.py                  # System constants
│   ├── recording/                    # Recording subsystem (modular design)
│   │   ├── manager.py                # Recording coordinator (public API)
│   │   └── __init__.py               # Recording module exports
│   ├── commands/                     # JSON command protocol
│   │   ├── command_handler.py        # Command processing
│   │   ├── command_protocol.py       # Command definitions
│   │   └── __init__.py               # Command exports
│   ├── config/                       # Configuration management
│   │   ├── config_loader.py          # Config file loading
│   │   └── __init__.py               # Config exports
│   ├── modes/                        # Operation modes
│   │   ├── base_mode.py              # Base mode class
│   │   ├── interactive_mode.py       # Interactive mode with OpenCV preview
│   │   ├── slave_mode.py             # JSON command-driven mode
│   │   ├── headless_mode.py          # Background tracking mode
│   │   └── __init__.py               # Mode exports
│   └── __init__.py                   # Package exports
└── recordings/                       # Session recordings (auto-created)
    └── tracking_YYYYMMDD_HHMMSS/     # Timestamped session directories
```

## Session Output

Each runtime spawns a dedicated session folder inside the configured `--output-dir` directory:

**Directory Structure:**
```
recordings/
└── tracking_YYYYMMDD_HHMMSS/
    ├── session.log                           # System log file
    ├── scene_video_TIMESTAMP.mp4            # Scene camera video
    ├── gaze_data_TIMESTAMP.csv              # Gaze coordinates and timestamps
    ├── gaze_full_TIMESTAMP.csv              # Extended gaze metrics (if enabled)
    ├── imu_data_TIMESTAMP.csv               # IMU sensor data (if available)
    ├── events_TIMESTAMP.csv                 # Eye tracking events (if available)
    ├── audio_TIMESTAMP.wav                  # Headset audio track (if enabled)
    ├── audio_timing_TIMESTAMP.csv           # Audio timing metadata (if enabled)
    ├── frame_timing_TIMESTAMP.csv           # Frame timing metadata
    └── device_status_TIMESTAMP.csv          # Device telemetry log (if enabled)
```

**Log File:**
- `session.log` — Complete system log for the session
  - **All output captured:** Python logging + system messages
  - All tracker system events, errors, and status messages
  - Paired with recordings for easy troubleshooting
  - Log level configurable via `log_level` in config.txt or `--log-level` CLI argument
  - Console output disabled by default (logs to file only)
  - Use `tail -f session.log` to monitor logs in real-time

**Data Files:**
- `scene_video_TIMESTAMP.mp4` — Scene camera video with gaze overlay
- `gaze_data_TIMESTAMP.csv` — Gaze position data with timestamps
- `gaze_full_TIMESTAMP.csv` — Per-eye gaze metrics (pupil diameter, eyelids, etc.)
- `imu_data_TIMESTAMP.csv` — IMU sensor data (accelerometer, gyroscope)
- `events_TIMESTAMP.csv` — Eye tracking events (blinks, fixations, etc.)
- `frame_timing_TIMESTAMP.csv` — Frame timing diagnostics
- `audio_TIMESTAMP.wav` — Raw headset microphone audio (AAC decoded to WAV)
- `audio_timing_TIMESTAMP.csv` — Samples/clock metadata for audio stream
- `device_status_TIMESTAMP.csv` — Battery/memory/sensor state snapshots during recording

## Architecture

### System Overview

The eye tracking system uses an **async architecture** for optimal performance:

```
Pupil Labs Eye Tracker (Network/RTSP)
    ↓
DeviceManager → discovers and connects to device
    ↓
StreamHandler → manages RTSP streams (video, gaze, IMU, events)
    ↓
GazeTracker → orchestrates processing pipeline
    ├→ FrameProcessor → adds overlays and displays via OpenCV
    ├→ RecordingManager → modular recording subsystem
    │   └→ CSV/Video Writers → synchronized data export
    └→ Mode Handler → interactive/headless/slave
```

**Key Features:**
- **Flexible FPS**: Supports 1-120 FPS processing (device-dependent)
- **Async Architecture**: Fully async/await patterns with asyncio
- **Stream Synchronization**: Aligns gaze, IMU, and video streams
- **Modular Recording**: Recording subsystem split into focused components

### Standalone Mode (Interactive)
- **With OpenCV Preview**:
  - Real-time gaze overlay on scene video
  - FPS display and frame counters
  - Keyboard controls (q/r)
  - Direct tracker control

### Slave Mode
- **Without Preview** (default):
  - No GUI interface (pure headless operation)
  - JSON command protocol via stdin/stdout
  - Real-time status reporting to master process
- Signal handling for graceful shutdown (SIGTERM, SIGINT)

### Headless Mode
- Continuous tracking without preview (auto-starts)
- Minimal CPU overhead
- Suitable for long-running background tracking
- Can be combined with auto-recording for unattended operation

## Performance Characteristics

- **Low Latency**: <50ms gaze-to-video latency (device-dependent)
- **Efficient I/O**: Async file operations with optimized buffering
- **Minimal CPU Usage**: ~10-15% CPU at 30 FPS on Raspberry Pi 5
- **Stream Synchronization**: Sub-millisecond timestamp alignment
- **Auto-Recovery**: Automatic device discovery retry on failure

## Dependencies

- **pupil-labs-realtime-api**: Pupil Labs device communication
- **opencv-python**: Video processing and display
- **numpy**: Array operations
- **cli_utils**: Shared CLI utilities (from parent project)

All dependencies are managed via `uv` package manager.

## Troubleshooting

### Common Issues

1. **No devices detected:**
   - Check network connectivity
   - Verify eye tracker is powered on and connected
   - Ensure devices appear in network scan
   - Check firewall settings (RTSP port 8086)

2. **Recording fails to start:**
   - Kill existing processes: `pkill -f main_tracker`
   - Check device isn't locked by another application
   - Verify storage has sufficient space

3. **Import Errors:**
   - Always use `uv run` instead of direct Python execution
   - Ensure you've run `uv sync` to install dependencies
   - Verify PYTHONPATH includes project root

4. **Permission Issues:**
   - Ensure user has write permissions to output directory

### Hardware Setup

1. Connect Pupil Labs eye tracker to network
2. Verify device connectivity: Check Pupil Labs Companion app
3. Use fast storage for recording (USB 3.0 recommended)
4. Ensure adequate power supply

## Examples

### Basic Tracking Session

```bash
# Start interactive mode with default settings (5 FPS, 720p)
uv run main_tracker.py --mode interactive

# Controls:
# Press 'r' to start/stop recording
# Press 'q' to quit
```

### Programmatic Control

```python
import subprocess
import json
import time

# Start tracker in slave mode
proc = subprocess.Popen(
    ["uv", "run", "main_tracker.py", "--mode", "slave"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=0
)

# Wait for ready status
while True:
    line = proc.stdout.readline()
    if line and line.startswith('{'):
        msg = json.loads(line)
        if msg.get('status') == 'ready':
            print("System ready!")
            break

# Start recording
proc.stdin.write(json.dumps({"command": "start_recording"}) + "\n")
proc.stdin.flush()
status = json.loads(proc.stdout.readline())
print(f"Recording started: {status}")

# Record for 30 seconds
time.sleep(30)

# Stop recording
proc.stdin.write(json.dumps({"command": "stop_recording"}) + "\n")
proc.stdin.flush()
status = json.loads(proc.stdout.readline())
print(f"Recording stopped: {status}")

# Cleanup
proc.stdin.write(json.dumps({"command": "quit"}) + "\n")
proc.stdin.flush()
proc.wait(timeout=5)
```

## Related Modules

- `../Cameras/` - Camera recording module with parallel architecture
- `../AudioRecorder/` - Audio recording module
- `../../cli_utils.py` - Shared CLI argument parsing and utilities

## Support

For issues and questions, refer to the main project documentation in `/CLAUDE.md`.
