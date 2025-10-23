# RPi Logger - Master Logger System

A master orchestrator for managing multiple logging modules with a unified interface.

## Overview

The Master Logger discovers, launches, and controls multiple logging modules (Cameras, AudioRecorder, EyeTracker, NoteTaker) through a centralized system with:

- **Dynamic Module Discovery**: Automatically finds all modules in `Modules/` directory
- **Unified Interface**: Tkinter GUI with module selection checkboxes
- **Centralized Data**: All module outputs saved in organized session directories
- **Process Orchestration**: Manages module subprocesses via JSON command protocol
- **Async Architecture**: Pure asyncio design for efficient concurrency

## Available Modules

- **Cameras** - Multi-camera video recording with synchronized capture and overlay support
- **AudioRecorder** - Multi-channel audio recording with configurable sample rates
- **EyeTracker** - Pupil Labs eye tracking integration with gaze data and scene video
- **NoteTaker** - Timestamped note-taking interface for annotating sessions in real-time

Each module can run standalone with GUI or be controlled through the master logger.

## Quick Start

```bash
# Launch the master logger
python3 main_logger.py

# Or with custom settings
python3 main_logger.py --data-dir ~/my_data --session-prefix experiment

# Run individual modules standalone
python3 Modules/Cameras/main_camera.py --mode gui
python3 Modules/AudioRecorder/main_audio.py --mode gui
python3 Modules/EyeTracker/main_eye_tracker.py --mode gui
python3 Modules/NoteTaker/main_notes.py --mode gui
```

## Usage Workflow

1. **Launch and Select Modules**
   - Launch `main_logger.py`
   - **Check a module to immediately launch it** (Cameras, AudioRecorder, EyeTracker, NoteTaker)
   - **Uncheck a module to immediately stop it**
   - Status indicators show module state in real-time

2. **Start Recording**
   - Once modules show "● Ready" status
   - Click "Start Recording" to begin recording on all active modules
   - Recording timer shows elapsed time

3. **Stop Recording**
   - Click "Stop Recording" to stop recording (modules remain active)
   - To fully stop a module, uncheck its checkbox

4. **View Data**
   - All data saved in: `data/session_YYYYMMDD_HHMMSS/`
   - Each module has its own subdirectory
   - Master log: `master.log` in session directory

## Directory Structure

```
data/
└── session_20251014_120000/
    ├── master.log              # Master logger log
    ├── Cameras/                # Camera module output
    │   └── session_*/
    │       ├── session.log
    │       ├── camera0.h264
    │       └── camera1.h264
    ├── AudioRecorder/          # Audio module output
    │   └── experiment_*/
    │       ├── session.log
    │       └── *.wav files
    ├── EyeTracker/             # Eye tracker output
    │   └── tracking_*/
    │       ├── session.log
    │       ├── gaze_*.csv
    │       └── scene_video.mp4
    └── NoteTaker/              # Note taking output
        └── notes_*/
            ├── session.log
            └── notes.csv
```

## Module Details

### Cameras Module
- Supports multiple simultaneous camera streams
- Configurable resolution, framerate, and encoding
- Real-time preview with overlay information
- Synchronized capture across all cameras

### AudioRecorder Module
- Multi-channel audio recording
- Configurable sample rates and bit depths
- Real-time level monitoring
- Support for multiple audio devices

### EyeTracker Module
- Integration with Pupil Labs eye tracking hardware
- Real-time gaze tracking and pupil detection
- Scene camera video recording
- CSV export of gaze data with timestamps

### NoteTaker Module
- Timestamped note-taking during sessions
- Text entry with automatic timestamp recording
- CSV export of all notes with precise timestamps
- View note history during recording
- Useful for annotating events or observations during data collection

## Configuration

Edit `config.txt` in the project root to customize:

```ini
# Data directory
data_dir = data

# Session prefix
session_prefix = session

# Logging
log_level = info
console_output = true
```

## Command Line Options

```bash
--data-dir DIR              # Root directory for all logging data
--session-prefix PREFIX     # Prefix for session directories
--log-level LEVEL           # Logging level (debug/info/warning/error/critical)
--console                   # Also log to console
--no-console                # Log to file only
```

## Module Communication

The master logger communicates with modules via JSON protocol over stdin/stdout:

**Commands (Master → Module):**
- `start_recording` - Begin recording
- `stop_recording` - Stop recording
- `get_status` - Request status update
- `take_snapshot` - Capture snapshot
- `quit` - Graceful shutdown

**Status Messages (Module → Master):**
- `initialized` - Module ready
- `recording_started` - Recording active
- `recording_stopped` - Recording stopped
- `error` - Error occurred
- `status_report` - Status information

## Module Requirements

For a module to be compatible with the master logger:

1. **Entry Point**: `main_*.py` file (e.g., `main_camera.py`)
2. **Slave Mode**: Support `--mode slave` argument
3. **Output Directory**: Accept `--output-dir` to override default
4. **JSON Protocol**: Implement command/status protocol
5. **Async Architecture**: Use asyncio for concurrency

## Architecture

```
main_logger.py
    ↓
LoggerSystem (orchestrator)
    ↓
ModuleProcess (per module)
    ↓
Subprocess (module in slave mode)
    ↓
Module Core (camera_core, audio_core, tracker_core, notes_core)
    ↓
Shared Base Utilities (Modules/base/)
    - BaseSystem, BaseSupervisor
    - TkinterGuiBase, TkinterMenuBase
    - RecordingMixin, AsyncUtils
    - ConfigLoader, SessionUtils
```

All modules share common functionality through the base utilities, ensuring consistent behavior across the system.

## Module Status Indicators

- **● Idle** (gray) - Module not started
- **● Starting...** (orange) - Module launching
- **● Initializing...** (orange) - Module initializing hardware
- **● Ready** (green) - Module ready to record
- **● RECORDING** (red) - Module actively recording
- **● Error** (red) - Module encountered an error
- **● Crashed** (red) - Module process crashed

## Troubleshooting

### Modules Not Starting
- Check module logs in `data/session_*/ModuleName/session.log`
- Verify hardware is connected (cameras, microphones, eye tracker)
- Ensure no other processes are using the devices

### Recording Fails
- Check individual module status indicators
- Review module-specific configuration files
- Verify sufficient disk space

### UI Not Responding
- Check master log: `data/session_*/master.log`
- Ensure no blocking operations in main thread
- Restart the application

## Adding New Modules

To add a new logging module:

1. Create directory in `Modules/` (e.g., `Modules/NewSensor/`)
2. Implement `main_newsensor.py` entry point
3. Support `--mode slave --output-dir DIR` arguments
4. Implement JSON command protocol
5. Create `*_core/` directory with module logic
6. Restart master logger (module auto-discovered)

## Development

**Testing Module Discovery:**
```bash
python3 logger_core/module_discovery.py
```

**Testing Command Protocol:**
```bash
python3 logger_core/commands/command_protocol.py
```

**Manual Module Launch (for debugging):**
```bash
# Launch camera module in slave mode
uv run Modules/Cameras/main_camera.py --mode slave --output-dir /tmp/test
```

## License

Part of the RPi Logger project.
