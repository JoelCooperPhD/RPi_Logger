# RPi Logger - Multi-Modal Data Collection System

A professional multi-modal data collection system for automotive research on Raspberry Pi 5, featuring synchronized recording across cameras, microphones, eye tracking, and behavioral tasks.

## Overview

The RPi Logger is designed for in-vehicle data collection with precise synchronization across multiple sensor modalities. The system features:

- **Unified Control Interface**: Single application to control all recording modules
- **Multi-Modal Recording**: Cameras, microphones, eye tracking, behavioral tasks, and annotations
- **Frame-Level Synchronization**: Automatic A/V sync with ~30ms accuracy via timestamped CSVs
- **Modular Architecture**: Each module can run standalone or coordinated through master logger
- **Async Design**: Modern asyncio patterns for efficient concurrent operation
- **Session Management**: Organized data output with automatic timestamping

## System Features

### Hardware Integration
- **Multi-Camera Video**: Up to 2x cameras (tested with IMX296 Global Shutter) at 1-60 FPS
- **Multi-Channel Audio**: Multiple USB microphones with 8-192 kHz sampling
- **Eye Tracking**: Pupil Labs device integration with gaze data and scene video
- **sDRT Devices**: USB serial communication for detection response tasks
- **Hot-Plug Support**: Automatic device detection and reconnection

### Recording Capabilities
- **Trial-Based Recording**: Record multiple trials within a session
- **Synchronized Timestamps**: All modules capture `time.time()` and `time.perf_counter()`
- **CSV Timing Logs**: Per-module timestamped event logs for synchronization
- **Automatic Muxing**: Post-processing utility creates synchronized A/V files
- **Note Taking**: Timestamped annotations during data collection

### User Interface
- **Master Logger GUI**: Tkinter interface for module selection and control
- **Module GUIs**: Individual windows for each active module with real-time previews
- **Session Timer**: Live recording duration display
- **Status Indicators**: Real-time module state feedback
- **Window Management**: Automatic tiling and geometry restoration

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd RPi_Logger

# Install dependencies (using uv package manager)
uv sync
```

### Launch Master Logger

```bash
# Start the master logger
python -m rpi_logger

# Or with custom settings
python -m rpi_logger --data-dir ~/research_data --session-prefix experiment

# If older tooling expects a script, this still works:
python main_logger.py --mode gui
```

### Basic Workflow

1. **Launch Application**: Run `python -m rpi_logger`
2. **Select Modules**: Check boxes for desired modules (auto-launches)
3. **Start Session**: Click "Start Session" to prepare modules
4. **Record Trial**: Click "Record" to begin trial recording
5. **Stop Trial**: Click "Stop" to end trial (data saved automatically)
6. **End Session**: Click "End Session" to finalize
7. **Process Data**: Run `python -m rpi_logger.tools.muxing_tool` and select the session folder
   (CLI alternative: `python -m rpi_logger.tools.sync_and_mux <session_dir> --all-trials`)

## Available Modules

### Cameras
Multi-camera video recording with hardware-accelerated H.264 encoding, real-time preview, and frame-level timing diagnostics.

**Key Features:**
- 1-60 FPS capture with IMX296 sensors
- H.264 hardware encoding (GPU-accelerated)
- Per-frame CSV timing logs with sensor timestamps
- Dropped frame detection via timestamp analysis
- Configurable resolution presets (320x240 to 1456x1088)

**Standalone Usage:**
```bash
python3 Modules/Cameras/main_camera.py --resolution 2 --target-fps 30
```

### AudioRecorder
Multi-microphone recording with USB hot-plug support and configurable sample rates.

**Key Features:**
- 8-192 kHz sample rate support
- 16-bit PCM WAV encoding
- Per-chunk CSV timing logs
- Automatic USB device detection
- Multiple device simultaneous recording

**Standalone Usage:**
```bash
python3 Modules/AudioRecorder/main_audio.py --sample-rate 48000
```

### EyeTracker
Pupil Labs eye tracking integration with gaze overlay and scene video recording.

**Key Features:**
- Network-based device discovery (RTSP)
- Real-time gaze, IMU, and event data
- Scene video with gaze overlay
- CSV export of all data streams
- Configurable processing FPS (1-120)

**Standalone Usage:**
```bash
python3 Modules/EyeTracker/main_eye_tracker.py --target-fps 30
```

### NoteTaker
Timestamped note-taking interface for annotating sessions in real-time.

**Key Features:**
- Millisecond-precision timestamps
- Session elapsed time tracking
- Records which modules are actively recording
- CSV export for analysis
- Keyboard shortcuts for rapid entry

**Standalone Usage:**
```bash
python3 Modules/NoteTaker/main_notes.py --mode gui
```

### DRT (Detection Response Task)
Multi-device sDRT (Simple Detection Response Task) support with USB serial communication.

**Key Features:**
- Automatic USB device detection (VID/PID filtering)
- Multi-device support with hot-plug
- Real-time scrolling plot (60-second window)
- ISO preset configuration (3-5s ISI, 1s stimulus)
- CSV logging of trial data

**Standalone Usage:**
```bash
python3 Modules/DRT/main_drt.py --mode gui
```

## Architecture

### System Layers

```
┌─────────────────────────────────────────────────────┐
│            rpi_logger/app/master.py                 │
│      (Package Entry Point & Coordination)          │
└──────────────────────┬──────────────────────────────┘
                       │
           ┌───────────┴───────────┐
           │    LoggerSystem       │
           │     (Facade)          │
           └───────────┬───────────┘
                       │
       ┌───────────────┼───────────────┐
       │               │               │
┌──────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐
│   Module    │ │  Session   │ │  Window    │
│   Manager   │ │  Manager   │ │  Manager   │
└─────────────┘ └────────────┘ └────────────┘
```

### Core Components

**LoggerSystem** (`logger_core/logger_system.py`)
- Facade pattern coordinator
- Unified API for UI
- Delegates to specialized managers

**ModuleManager** (`logger_core/module_manager.py`)
- Module discovery and lifecycle
- Process management for slave mode modules
- JSON command protocol communication

**SessionManager** (`logger_core/session_manager.py`)
- Session and trial coordination
- Cross-module recording synchronization
- State tracking

**ShutdownCoordinator** (`logger_core/shutdown_coordinator.py`)
- Race-condition-free shutdown
- Ordered cleanup callbacks
- State machine protection

**WindowManager** (`logger_core/window_manager.py`)
- Automatic window tiling
- Geometry persistence

### Module Architecture

Each module follows a consistent pattern:

```
Module/
├── main_<module>.py          # Entry point
├── config.txt                # Configuration
├── <module>_core/            # Core implementation
│   ├── <module>_system.py    # System coordinator
│   ├── <module>_supervisor.py # Lifecycle management
│   ├── <module>_handler.py   # Device/sensor handler
│   ├── recording/            # Recording subsystem
│   │   └── manager.py        # Recording coordinator
│   ├── interfaces/gui/       # GUI implementation
│   │   └── tkinter_gui.py    # Tkinter interface
│   ├── commands/             # JSON command protocol
│   │   └── command_handler.py
│   ├── modes/                # Operation modes
│   │   ├── gui_mode.py       # Standalone GUI mode
│   │   └── headless_mode.py  # Slave mode (master logger control)
│   └── config/               # Config management
└── recordings/               # Output directory
```

### Shared Base Classes

All modules inherit from common base classes in `Modules/base/`:

- `BaseSystem`: Core system interface
- `BaseSupervisor`: Lifecycle and retry logic
- `TkinterGuiBase`: Common GUI functionality
- `RecordingMixin`: Recording state management
- `ConfigLoader`: Configuration file handling

## Session Data Structure

```
data/
└── session_20251024_120000/
    ├── master.log                                      # Master logger log
    ├── 20251024_120000_SYNC_trial001.json             # Sync metadata
    ├── 20251024_120000_AV_trial001.mp4                # Muxed audio/video
    ├── Cameras/
    │   ├── session.log
    │   ├── 20251024_120000_CAM_trial001_CAM0_1456x1088_30fps.mp4
    │   └── 20251024_120000_CAMTIMING_trial001_CAM0.csv
    ├── AudioRecorder/
    │   ├── session.log
    │   ├── 20251024_120000_AUDIO_trial001_MIC0_usb-audio.wav
    │   └── 20251024_120000_AUDIOTIMING_trial001_MIC0.csv
    ├── EyeTracker/
    │   ├── session.log
    │   ├── scene_video_20251024_120000.mp4
    │   ├── gaze_data_20251024_120000.csv
    │   └── frame_timing_20251024_120000.csv
    ├── NoteTaker/
    │   ├── session.log
    │   └── session_notes.csv
    └── DRT/
        ├── session.log
        └── sDRT_dev_ttyACM0_20251024_120000.csv
```

## Audio-Video Synchronization

The system implements **frame-level synchronization** (~30ms accuracy) through:

1. **Timestamp Capture**: Each module captures `time.time()` at recording start
2. **CSV Timing Logs**: Per-event timestamps for all data (frames, chunks, samples)
3. **Sync Metadata**: Unified JSON file with timing for all modules
4. **Automatic Muxing**: `python -m rpi_logger.tools.muxing_tool` (FFmpeg) combines streams with calculated offsets

### File Naming Convention

All files use consistent trial-based naming:

- Audio: `{timestamp}_AUDIO_trial{N:03d}_MIC{id}_{name}.wav`
- Video: `{timestamp}_CAM_trial{N:03d}_CAM{id}_{w}x{h}_{fps}fps.mp4`
- Audio CSV: `{timestamp}_AUDIOTIMING_trial{N:03d}_MIC{id}.csv`
- Video CSV: `{timestamp}_CAMTIMING_trial{N:03d}_CAM{id}.csv`
- Sync Metadata: `{timestamp}_SYNC_trial{N:03d}.json`
- Muxed Output: `{timestamp}_AV_trial{N:03d}.mp4`

### Processing Recordings

```bash
# Interactive helper (select folder if --session omitted)
python -m rpi_logger.tools.muxing_tool --session data/session_20251024_120000

# Process all trials via CLI
python -m rpi_logger.tools.sync_and_mux data/session_20251024_120000 --all-trials

# Process specific trial
python -m rpi_logger.tools.sync_and_mux data/session_20251024_120000 --trial 2

# Generate sync metadata only (skip muxing)
python -m rpi_logger.tools.sync_and_mux data/session_20251024_120000 --no-mux
```

## Configuration

### Main Configuration (`config.txt`)

```ini
# Paths
data_dir = data
session_prefix = session

# Logging
log_level = info
console_output = false

# UI
window_x = 100
window_y = 100
window_width = 800
window_height = 600

# Session restore
last_session_dir = /path/to/last/session
```

### Module Configuration

Each module has its own `config.txt` with:
- `enabled` - Auto-start with master logger
- Module-specific settings (resolution, sample rate, etc.)
- Window geometry (auto-saved)
- Logging configuration

### AV Muxing Configuration (`Modules/base/constants.py`)

```python
AV_MUXING_ENABLED = True          # Enable automatic muxing
AV_MUXING_TIMEOUT_SECONDS = 60    # FFmpeg timeout
AV_DELETE_SOURCE_FILES = False    # Keep originals after mux
```

## Command Line Options

### Main Logger

```bash
--data-dir DIR              # Root directory for logging data
--session-prefix PREFIX     # Prefix for session directories
--log-level LEVEL           # Logging level (debug/info/warning/error/critical)
--console                   # Also log to console
--no-console                # Log to file only (default)
```

### Module-Specific

See individual module README files for detailed options.

## Module Communication Protocol

The master logger communicates with modules via **JSON protocol over stdin/stdout**:

### Commands (Master → Module)

```json
{"command": "start_session", "session_dir": "/path/to/session"}
{"command": "start_recording"}
{"command": "stop_recording"}
{"command": "end_session"}
{"command": "get_status"}
{"command": "quit"}
```

### Status Messages (Module → Master)

```json
{
  "type": "status",
  "status": "initialized|recording_started|recording_stopped|error",
  "timestamp": "ISO-8601 timestamp",
  "data": { /* module-specific data */ }
}
```

## Module Status Indicators

- **○ Stopped** - Module not running
- **○ Starting...** - Module launching
- **○ Initializing...** - Hardware initialization
- **● Ready** (green) - Ready to record
- **● RECORDING** (red) - Actively recording
- **● Error** (red) - Error encountered
- **● Crashed** (red) - Process crashed

## Development

### Project Structure

```
RPi_Logger/
├── rpi_logger/             # Application package (entrypoints + tooling)
│   ├── __main__.py         # Enables ``python -m rpi_logger``
│   ├── app/master.py       # Master logger orchestration
│   ├── cli/common.py       # Shared CLI helpers for modules
│   └── tools/              # Post-processing and diagnostics utilities
├── main_logger.py          # Thin script that forwards to the packaged entrypoint
├── config.txt              # Main configuration
├── CLAUDE.md               # Architecture documentation
├── README.md               # This file
├── logger_core/            # Master logger core
│   ├── logger_system.py    # System facade
│   ├── module_manager.py   # Module lifecycle
│   ├── session_manager.py  # Session/trial control
│   ├── shutdown_coordinator.py # Graceful shutdown
│   ├── window_manager.py   # Window layout
│   ├── config_manager.py   # Config handling
│   ├── paths.py            # Path constants
│   ├── event_logger.py     # Event logging
│   └── ui/                 # User interface
│       ├── main_window.py  # Main GUI window
│       ├── main_controller.py # UI event handler
│       ├── timer_manager.py # Recording timers
│       └── help_dialogs.py # Help windows
├── Modules/                # Recording modules
│   ├── base/               # Shared base classes
│   │   ├── base_system.py
│   │   ├── base_supervisor.py
│   │   ├── tkinter_gui_base.py
│   │   ├── recording.py
│   │   ├── io_utils.py
│   │   ├── constants.py
│   │   ├── sync_metadata.py # Sync metadata writer
│   │   ├── av_muxer.py     # FFmpeg A/V muxer
│   │   └── usb_serial_manager.py # USB device framework
│   ├── Cameras/            # Camera module
│   ├── AudioRecorder/      # Audio module
│   ├── EyeTracker/         # Eye tracking module
│   ├── NoteTaker/          # Note taking module
│   └── DRT/                # DRT task module
└── data/                   # Session recordings (auto-created)
```

### Testing

```bash
# Syntax check core files
python -m py_compile rpi_logger/app/master.py
python -m py_compile logger_core/*.py

# Test module in standalone mode
python3 Modules/Cameras/main_camera.py
python3 Modules/AudioRecorder/main_audio.py

# Test with master logger
python -m rpi_logger
```

### Adding New Modules

To create a new module:

1. **Copy Template**: Use existing module as template (e.g., NoteTaker for simple modules)
2. **Implement Core**: Create `<module>_system.py` inheriting from `BaseSystem`
3. **Add Recording**: Implement recording manager with `get_sync_metadata()` method
4. **Create GUI**: Inherit from `TkinterGuiBase` for consistency
5. **Add Modes**: Implement GUI and headless modes
6. **Command Protocol**: Implement JSON command handler
7. **Configure**: Create `config.txt` with module settings
8. **Document**: Add README.md with usage instructions

## Troubleshooting

### Modules Not Starting

**Symptoms**: Module shows "Error" or "Crashed" status

**Solutions**:
- Check module log in `data/session_*/ModuleName/session.log`
- Verify hardware is connected (cameras, microphones, eye tracker)
- Ensure no other processes are using devices: `pkill -f main_camera`
- Check permissions for audio/video devices

### Recording Fails

**Symptoms**: "Record" button doesn't start recording or stops immediately

**Solutions**:
- Check individual module status indicators
- Review module-specific configuration files
- Verify sufficient disk space: `df -h`
- Check module logs for specific errors

### Synchronization Issues

**Symptoms**: Audio/video out of sync in muxed output

**Solutions**:
- Verify timing CSV files exist for both audio and video
- Check timestamps in SYNC.json are reasonable
- Ensure FFmpeg is installed: `which ffmpeg`
- Try manual muxing with custom offset

### UI Not Responding

**Symptoms**: GUI freezes or becomes unresponsive

**Solutions**:
- Check master log: `data/session_*/master.log`
- Kill processes: `pkill -f rpi_logger.app.master` (or `pkill -f main_logger.py` if launched via the script)
- Restart system
- Check for blocking operations in logs

### USB Device Detection

**Symptoms**: Audio devices or DRT devices not detected

**Solutions**:
- Verify device shows in system: `lsusb` and `arecord -l`
- Add user to audio group: `sudo usermod -a -G audio $USER`
- Check VID/PID in module config.txt
- Restart device or replug USB

## Hardware Requirements

### Raspberry Pi 5 (Recommended)

- **CPU**: Quad-core ARM Cortex-A76 @ 2.4GHz
- **RAM**: 4GB minimum, 8GB recommended
- **Storage**: 32GB+ microSD or USB 3.0 SSD
- **Cooling**: Active cooling required for multi-camera operation
- **Power**: Official 27W USB-C power supply

### Supported Hardware

- **Cameras**: Up to 2x CSI cameras (tested: IMX296 Global Shutter)
- **Microphones**: Multiple USB audio input devices
- **Eye Tracker**: Pupil Labs (Invisible/Neon) via network
- **DRT Devices**: USB serial devices (Adafruit Trinket M0 tested)

### Storage Recommendations

- **Class 10+ microSD**: Minimum for single-camera recording
- **USB 3.0 SSD**: Recommended for multi-camera + audio
- **Estimate**: ~500 MB/min for 1x camera (720p@30fps) + 1x mic (48kHz)

## Dependencies

All dependencies managed via `uv` package manager:

```bash
# Install all dependencies
uv sync

# Core dependencies
- python >= 3.9
- tkinter (usually included with Python)
- asyncio (standard library)

# Module-specific
- picamera2 (Cameras)
- opencv-python (Cameras, EyeTracker)
- sounddevice (AudioRecorder)
- numpy (multiple modules)
- pupil-labs-realtime-api (EyeTracker)
- pyserial (DRT)
- aiofiles (async file I/O)

# System tools
- ffmpeg (A/V muxing)
```

## Best Practices

### Recording Sessions

1. **Pre-flight Check**: Test all modules individually before integrated session
2. **Storage Space**: Verify adequate disk space before long sessions
3. **Battery/Power**: Ensure stable power supply (UPS recommended)
4. **Device Warmup**: Let cameras/sensors warm up for 30 seconds
5. **Post-Session**: Process recordings with `python -m rpi_logger.tools.muxing_tool` (or `python -m rpi_logger.tools.sync_and_mux`) immediately

### Configuration Management

1. **Backup Configs**: Keep backup of working `config.txt` files
2. **Module Defaults**: Set reasonable defaults in module configs
3. **CLI Overrides**: Use command-line args for one-off changes
4. **Logging Levels**: Use `info` for production, `debug` for troubleshooting

### Development Workflow

1. **Syntax Check**: Always run `python -m py_compile` before testing
2. **Standalone Testing**: Test modules individually before integration
3. **Log Review**: Check logs after every session for warnings
4. **Type Hints**: Maintain type annotations for all functions
5. **Async Patterns**: Use `asyncio.to_thread()` for blocking I/O

## Performance

### Typical Resource Usage (RPi 5)

- **CPU**: 30-40% with 2x cameras + audio + eye tracker
- **RAM**: ~500 MB for master logger + all modules
- **Disk I/O**: ~8 MB/s for 2x 720p cameras + 2x 48kHz mics
- **Network**: ~2 Mbps for eye tracker stream

### Optimization Tips

1. **Camera Resolution**: Use 720p instead of 1080p to reduce CPU/disk usage
2. **Audio Sample Rate**: 48kHz is sufficient for most applications
3. **Preview Windows**: Disable previews in slave mode for lower CPU usage
4. **Eye Tracker FPS**: 5-10 FPS is sufficient for most gaze tracking
5. **CSV Logging**: Disable if not needed for synchronization

## License

Part of the RPi Logger project.

## Contributing

For issues, feature requests, or contributions, please refer to the main project repository.

## Support

- **Documentation**: See `CLAUDE.md` for architecture details
- **Module Docs**: See individual `Modules/*/README.md` files
- **Utilities**: See `rpi_logger/tools/README.md` for post-processing tools

---

**Version**: October 2025
**Platform**: Raspberry Pi 5 / Raspberry Pi OS Bookworm
**Python**: 3.9+
