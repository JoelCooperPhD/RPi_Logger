# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RPiLogger - A comprehensive logging and camera system for Raspberry Pi 5 with multi-camera support.

**Key Components:**
- Multi-camera recording system with master-slave architecture
- Real-time preview with OpenCV integration
- JSON command protocol for programmatic control
- Flexible camera configuration

## Development Environment

- Platform: Raspberry Pi 5 (Linux ARM)
- OS: Linux 6.12.34+rpt-rpi-2712
- Working Directory: /home/rs-pi-2/Development/RPi_Logger
- Package Manager: uv (Python package manager)
- Camera Hardware: Multiple camera support (tested with 2x IMX296)

## Project Structure

```
RPi_Logger/
├── Modules/
│   └── Cameras/
│       ├── camera_module.py         # Main multi-camera system
│       ├── camera_master.py         # Example master control program
│       ├── README.md                # Module documentation
│       └── picamera2_reference.md   # Technical reference
├── CLAUDE.md                        # This file
└── [output directories]             # Recording/snapshot outputs (auto-created)
```

## Key Features

### Camera Module (`camera_module.py`)
- **Standalone Mode**: Interactive preview with keyboard controls
- **Slave Mode**: Command-driven operation for master-slave architecture
- **Signal Handling**: Graceful shutdown with SIGTERM/SIGINT
- **JSON Communication**: stdin/stdout protocol for commands/status

### Usage Examples

**Standalone Mode:**
```bash
uv run camera_module.py --width 1280 --height 720 --fps 25
```

**Slave Mode:**
```bash
uv run camera_module.py --slave --output recordings
```

**Master Control:**
```bash
uv run camera_master.py
```

### Commands (Slave Mode)
- `start_recording` - Begin recording all cameras
- `stop_recording` - Stop recording
- `take_snapshot` - Capture snapshots from all cameras
- `get_status` - Get system status
- `quit` - Graceful shutdown

## Testing

Run comprehensive test suite:
```bash
uv run camera_module.py --help
```

Test individual components:
```bash
uv run camera_master.py
```

## Development Notes

**Hardware Considerations:**
- Raspberry Pi 5 with adequate cooling recommended
- Multiple cameras require proper ribbon cable connections
- Consider CPU/memory constraints during development

**Dependencies:**
- All dependencies are ARM-compatible via uv
- Key libraries: picamera2, opencv-python, numpy

**Testing:**
- Always test on actual hardware (camera dependencies)
- Use `uv run` for all Python script execution
- Clean up camera processes between tests to avoid "device busy" errors

**Process Management:**
- Camera resources must be properly released
- Use signal handlers for graceful shutdown
- Master-slave communication uses JSON over stdin/stdout

## Common Issues

1. **Camera Busy Error**: Kill existing camera processes with `pkill -f camera_module`
2. **Import Errors**: Use `uv run` instead of direct Python execution
3. **Permission Issues**: Ensure user is in camera/video groups