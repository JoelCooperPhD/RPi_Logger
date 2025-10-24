# Audio Recorder Module

A professional multi-microphone audio recording system for Raspberry Pi with USB hot-plug support, synchronized timestamping for A/V muxing, and flexible control modes.

## Features

🎙️ **Multi-Device Support**: Simultaneous recording from multiple USB audio devices (tested with multiple USB microphones)
🎵 **High-Quality Recording**: 16-bit PCM WAV encoding with configurable sample rates (8-192 kHz)
🔌 **USB Hot-Plug**: Automatic detection (5ms polling) and handling of device connections/disconnections
⏱️ **Precise Timing**: Per-chunk CSV logs with Unix timestamps for ~30ms A/V sync accuracy
🔄 **Multiple Modes**: Standalone (interactive), headless, and slave (master logger) modes
🖱️ **Interactive Controls**: Keyboard shortcuts in standalone mode (r=record, s=status, q=quit)
⚙️ **Flexible Configuration**: Multiple sample rates, auto-device-selection, output options
🛡️ **Signal Handling**: Graceful shutdown with proper resource cleanup
📁 **Trial-Based Output**: Consistent naming for integration with sync_and_mux.py

## Hardware Requirements

- **Raspberry Pi 5** (or compatible Raspberry Pi models)
- **USB Audio Input Devices** (tested with multiple USB microphones)
- **Fast Storage** (Class 10+ SD card or USB 3.0 storage recommended)
- **Operating System**: Raspberry Pi OS Bullseye or later

## Quick Start

> **Automatic device detection:** The system automatically detects all connected USB audio input devices regardless of port or count. No configuration needed - just connect your microphones and start recording!

### Standalone Mode (Interactive)

```bash
# Start audio system with default settings (48 kHz sample rate)
uv run main_audio.py

# CD quality recording (44.1 kHz)
uv run main_audio.py --sample-rate 44100

# Custom output directory
uv run main_audio.py --output-dir recordings/my_session

# High-resolution audio (96 kHz)
uv run main_audio.py --sample-rate 96000

# Auto-start recording immediately on startup
uv run main_audio.py --auto-start-recording

# Monitor logs in real-time (in another terminal)
tail -f recordings/experiment_*/session.log
```

### Slave Mode (Master Logger Control)

```bash
# Typically launched automatically by main logger, but can be tested manually:
uv run main_audio.py --mode headless --output-dir data/session_test/AudioRecorder
```

### Integration with Main Logger

The audio module is typically used via the master logger (`main_logger.py`), which:
- Automatically launches the module in headless/slave mode
- Sends JSON commands for session/recording control
- Receives status updates and handles module lifecycle
- Coordinates synchronization across all modules

## Usage Modes

### Standalone Mode Controls

**With Console:**
- **`r`** + Enter: Toggle recording on/off
- **`s`** + Enter: Show device status
- **`1-9`** + Enter: Toggle device selection (device ID)
- **`q`** + Enter: Quit application
- **Ctrl+C**: Also quits gracefully

### Slave Mode Commands

Send JSON commands via stdin when running in `--mode slave`:

```json
{"command": "start_recording"}
{"command": "stop_recording"}
{"command": "get_status"}
{"command": "toggle_device", "device_id": 2, "enabled": true}
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
- `sample_rate` - Recording sample rate (8000-192000 Hz)
- `auto_start_recording` - Automatically start recording on startup (true/false)
- `auto_select_new` - Auto-select newly detected devices (true/false)
- `output_dir`, `session_prefix` - Output configuration

**Logging Settings:**
- `log_level` - Python logging verbosity (debug, info, warning, error, critical)
- `console_output` - Also print logs to console (true/false, default: false)

**Advanced Settings:**
- `discovery_timeout` - Device discovery timeout (seconds)
- `discovery_retry` - Retry interval after failure (seconds)

> **Note**: CLI arguments always override config.txt values. Edit `config.txt` to change defaults.

> **Logging Behavior**: All output is captured in `session.log`. ANSI color codes are automatically stripped for clean formatting. With `--console`, Python logging also writes to console. Use `tail -f recordings/experiment_*/session.log` to monitor logs in real-time.

### CLI Arguments

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--sample-rate` | 48000 | Recording sample rate in Hz (8000-192000) |
| `--output-dir` | `recordings` | Output directory for session folders |
| `--mode` | interactive | Execution mode (`interactive`, `slave`, `headless`) |
| `--session-prefix` | experiment | Prefix for generated session folders |
| `--auto-start-recording` | False | Automatically start recording on startup |
| `--no-auto-start-recording` | - | Wait for manual recording command (default) |
| `--auto-select-new` | True | Auto-select newly detected devices (default) |
| `--no-auto-select-new` | - | Disable automatic device selection |
| `--console` | False | Also log to console (in addition to file) |
| `--no-console` | - | Log to file only (no console output, default) |
| `--log-level` | info | Python logging verbosity (debug/info/warning/error/critical) |
| `--discovery-timeout` | 5.0 | Device discovery timeout (seconds) |
| `--discovery-retry` | 3.0 | Retry interval after device failure (seconds) |

**Sample Rate Presets:**
- 8000 Hz - Phone quality
- 16000 Hz - Wide-band speech
- 22050 Hz - Low quality music
- 44100 Hz - CD quality
- 48000 Hz - Professional audio (default)
- 96000 Hz - High-resolution audio
- 192000 Hz - Ultra high-resolution

> **Note**: Most settings can also be configured in `config.txt` to avoid passing CLI arguments. CLI arguments override config file values.

## File Structure

```
AudioRecorder/
├── main_audio.py                    # Main multi-microphone system entry point
├── README.md                        # This documentation
├── config.txt                       # System configuration (sample rate, logging settings)
├── audio_core/                      # Core audio system modules
│   ├── audio_handler.py             # Single device coordinator
│   ├── audio_system.py              # Multi-device system with interactive/slave/headless modes
│   ├── audio_supervisor.py          # Async supervisor with retry logic
│   ├── audio_utils.py               # Utilities (device discovery, config helpers)
│   ├── constants.py                 # System constants
│   ├── recording/                   # Recording subsystem (modular design)
│   │   ├── manager.py               # Recording coordinator (public API)
│   │   └── __init__.py              # Recording module exports
│   ├── commands/                    # JSON command protocol
│   │   ├── command_handler.py       # Command processing
│   │   ├── command_protocol.py      # Command definitions
│   │   └── __init__.py              # Command exports
│   ├── config/                      # Configuration management
│   │   ├── config_loader.py         # Config file loading
│   │   └── __init__.py              # Config exports
│   ├── modes/                       # Operation modes
│   │   ├── base_mode.py             # Base mode class
│   │   ├── interactive_mode.py      # Interactive mode with keyboard controls
│   │   ├── slave_mode.py            # JSON command-driven mode
│   │   ├── headless_mode.py         # Background recording mode
│   │   └── __init__.py              # Mode exports
│   └── __init__.py                  # Package exports
└── recordings/                      # Session recordings (auto-created)
    └── experiment_YYYYMMDD_HHMMSS/  # Timestamped session directories
```

## Session Output

Each runtime spawns a dedicated session folder inside the configured `--output-dir` directory:

**Directory Structure:**
```
recordings/
└── experiment_YYYYMMDD_HHMMSS/
    ├── session.log                                    # System log file
    ├── mic2_USB_Audio_Device_rec001_HHMMSS.wav      # Device 2 recording
    ├── mic5_Blue_Microphones_rec001_HHMMSS.wav      # Device 5 recording
    └── mic8_Logitech_Webcam_rec001_HHMMSS.wav       # Device 8 recording
```

**Log File:**
- `session.log` — Complete system log for the session
  - **All output captured:** Python logging + system messages
  - All audio system events, errors, and status messages
  - Paired with recordings for easy troubleshooting
  - Log level configurable via `log_level` in config.txt or `--log-level` CLI argument
  - Console output disabled by default (logs to file only)
  - Use `tail -f session.log` to monitor logs in real-time

**Audio Files:**
- Trial-based naming: `{timestamp}_AUDIO_trial{N:03d}_MIC{id}_{name}.wav`
- Example: `20251024_120000_AUDIO_trial001_MIC0_usb-audio.wav`
- 16-bit PCM WAV format (mono per device)
- Sample rate as configured (default: 48 kHz)
- Professional quality suitable for analysis and archival
- Used by `sync_and_mux.py` for A/V muxing

**Timing CSV:**
- Trial-based naming: `{timestamp}_AUDIOTIMING_trial{N:03d}_MIC{id}.csv`
- Example: `20251024_120000_AUDIOTIMING_trial001_MIC0.csv`
- **Columns:** `trial`, `chunk_number`, `write_time_unix`, `frames_in_chunk`, `total_frames`
- Used by `sync_and_mux.py` for A/V synchronization (~30ms accuracy)
- Chunk timestamps captured every ~21ms (1024 samples @ 48kHz)

## Architecture

### System Overview

The audio system uses an **async architecture** for optimal performance:

```
USB Audio Devices (configurable 8-192 kHz)
    ↓
AudioHandler (per device) → manages individual device streams
    ↓
AudioSystem → coordinates multiple devices
    ├→ Device Discovery → automatic USB device detection
    ├→ Recording Manager → modular recording subsystem
    │   └→ WAV Encoder → 16-bit PCM encoding
    └→ Mode Handler → interactive/slave/headless
```

**Key Features:**
- **Flexible Sample Rates**: Supports 8 kHz to 192 kHz (hardware dependent)
- **Async Architecture**: Fully async/await patterns with sounddevice library
- **Zero-Copy Pipeline**: Direct buffer access for minimal overhead
- **Modular Recording**: Recording subsystem split into focused components
- **USB Hot-Plug**: Real-time device detection via /proc/asound (5ms polling)

### Standalone Mode (Interactive)
- **With Console**:
  - Keyboard controls (r/s/1-9/q)
  - Real-time status display
  - USB device monitoring with automatic refresh
  - Direct device control
  - Lower CPU usage than headless

### Slave Mode
- **Without Console** (default):
  - No terminal interface (pure headless operation)
  - JSON command protocol via stdin/stdout
  - Real-time status reporting to master process
- Signal handling for graceful shutdown (SIGTERM, SIGINT)

### Headless Mode
- Continuous recording without interaction (auto-starts)
- Minimal CPU overhead
- Suitable for long-running background recording
- Can be combined with auto-device-selection for unattended operation

## Performance Characteristics

- **Low Latency**: <5ms device detection polling
- **Efficient I/O**: Async file operations with thread pool executors
- **Minimal CPU Usage**: Hardware-dependent, typically <5% per device at 48 kHz
- **USB Hot-Plug**: Ultra-fast detection via `/proc/asound/cards` (~5ms polling)
- **Concurrent Recording**: Multiple devices recorded in parallel with independent buffers
- **Auto-Recovery**: Automatic device discovery retry on failure

## Dependencies

- **sounddevice**: Audio I/O
- **numpy**: Audio data processing
- **aiofiles**: Async file operations
- **cli_utils**: Shared CLI utilities (from parent project)

All dependencies are managed via `uv` package manager.

## Troubleshooting

### Common Issues

1. **No devices detected:**
   - Check USB connections
   - Verify devices appear in `arecord -l`
   - Ensure user has audio permissions (add to `audio` group)

2. **Recording fails to start:**
   - Kill existing processes: `pkill -f main_audio`
   - Check device isn't locked by another application
   - Verify sample rate compatibility with your hardware

3. **Import Errors:**
   - Always use `uv run` instead of direct Python execution
   - Ensure you've run `uv sync` to install dependencies
   - Verify PYTHONPATH includes project root

4. **Permission Issues:**
   - Add user to audio group: `sudo usermod -a -G audio $USER`
   - Log out and back in for group changes to take effect

### Hardware Setup

1. Connect USB audio devices to Raspberry Pi USB ports
2. Verify device detection: `arecord -l`
3. Use fast storage for recording (USB 3.0 recommended for multiple high-resolution streams)
4. Ensure adequate power supply (multiple USB devices may require powered hub)

## Examples

### Basic Recording Session

```bash
# Start interactive mode with default settings (48 kHz)
uv run main_audio.py

# Controls:
# Press 'r' + Enter to start/stop recording
# Press 's' + Enter to show device status
# Press '1-9' + Enter to toggle device selection
# Press 'q' + Enter to quit
```

### Programmatic Control

```python
import subprocess
import json
import time
import select

# Start audio system in slave mode
proc = subprocess.Popen(
    ["uv", "run", "main_audio.py", "--mode", "slave"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,  # Merge stderr to stdout
    text=True,
    bufsize=0  # Unbuffered
)

def read_json_response(proc, timeout=5.0):
    """Helper to read JSON response, skipping non-JSON lines."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if select.select([proc.stdout], [], [], 0.1)[0]:
            line = proc.stdout.readline()
            if line and line.startswith('{'):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    pass
    return None

# Wait for system to be ready
print("Waiting for initialization...")
while True:
    msg = read_json_response(proc)
    if msg and msg.get('status') == 'ready':
        print("System ready!")
        break

# Send start recording command
proc.stdin.write(json.dumps({"command": "start_recording"}) + "\n")
proc.stdin.flush()
status = read_json_response(proc, timeout=10.0)  # Device init can take time
print(f"Recording started: {status.get('status')}")

# Record for 10 seconds
time.sleep(10)

# Stop recording
proc.stdin.write(json.dumps({"command": "stop_recording"}) + "\n")
proc.stdin.flush()
status = read_json_response(proc)
print(f"Recording stopped: {status.get('status')}")

# Get status
proc.stdin.write(json.dumps({"command": "get_status"}) + "\n")
proc.stdin.flush()
status = read_json_response(proc)
print(f"System status: {status}")

# Cleanup
proc.stdin.write(json.dumps({"command": "quit"}) + "\n")
proc.stdin.flush()
proc.wait(timeout=5)
```

> **Note**: Device initialization can take several seconds on first `start_recording`. The example includes appropriate timeouts to handle this.

## Related Modules

- `../Cameras/` - Camera recording module with parallel architecture
- `../EyeTracker/` - Eye tracking module
- `../../cli_utils.py` - Shared CLI argument parsing and utilities

## Support

For issues and questions, refer to the main project documentation in `/CLAUDE.md`.
