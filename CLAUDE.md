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

### Package Management with uv

This project uses `uv` for modern Python package management:

**Installation (if uv not available):**
```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh
# Or using pip
pip install uv
```

**Adding Dependencies:**
```bash
uv add package-name                    # Add runtime dependency
uv add --dev package-name              # Add development dependency
uv add package-name==1.2.3            # Add specific version
```

**Managing Environment:**
```bash
uv sync                                # Install all dependencies
uv lock                                # Update lock file
uv run python script.py               # Run with proper environment
uv shell                               # Activate virtual environment
```

**Project Commands:**
```bash
uv run --help                          # Show available scripts
uv tree                               # Show dependency tree
uv pip list                           # List installed packages
```

**Fallback (if uv unavailable):**
```bash
# Use traditional venv if uv not installed
source .venv/bin/activate
pip install package-name
python script.py
```

## Project Structure

```
RPi_Logger/
├── Modules/
│   └── Cameras/
│       ├── main_camera.py           # Main multi-camera system
│       ├── camera_master.py         # Example master control program
│       ├── README.md                # Module documentation
│       └── picamera2_reference.md   # Technical reference
├── CLAUDE.md                        # This file
└── [output directories]             # Recording/snapshot outputs (auto-created)
```

## Key Features

### Camera Module (`main_camera.py`)
- **Standalone Mode**: Interactive preview with keyboard controls
- **Slave Mode**: Command-driven operation for master-slave architecture
- **Signal Handling**: Graceful shutdown with SIGTERM/SIGINT
- **JSON Communication**: stdin/stdout protocol for commands/status

### Usage Examples

**Standalone Mode:**
```bash
uv run main_camera.py --width 1280 --height 720 --fps 25
```

**Slave Mode:**
```bash
uv run main_camera.py --mode slave --output-dir recordings/cameras
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
uv run main_camera.py --help
```

Test individual components:
```bash
uv run camera_master.py
```

## Development Notes

**Programming Patterns:**
- **Prefer asyncio**: Use modern async/await patterns for I/O operations, camera handling, and concurrent tasks
- **Async Best Practices**: Use `asyncio.gather()` for concurrent operations, `asyncio.Queue` for producer-consumer patterns
- **Resource Management**: Use `async with` context managers for camera resources and file operations
- **Error Handling**: Implement proper exception handling with `try/except` in async contexts

**Hardware Considerations:**
- Raspberry Pi 5 with adequate cooling recommended
- Multiple cameras require proper ribbon cable connections
- Consider CPU/memory constraints during development

**Dependencies:**
- All dependencies are ARM-compatible via uv
- Key libraries: picamera2, opencv-python, numpy, pupil-labs-realtime-api
- Use `uv add` to manage dependencies, not pip
- Note: uv path may be `/home/rs-pi-2/.local/bin/uv` if not in PATH

**Testing:**
- Always test on actual hardware (camera dependencies)
- Use `uv run` for all Python script execution
- Clean up camera processes between tests to avoid "device busy" errors

**Process Management:**
- Camera resources must be properly released
- Use signal handlers for graceful shutdown
- Master-slave communication uses JSON over stdin/stdout
- Implement async signal handling with `asyncio.create_task()`

**Hardware Documentation:**
- When working with specific hardware (cameras, sensors, etc.), always reference original manufacturer documentation
- For Raspberry Pi: Use official raspberrypi.com documentation and GPIO pinout references
- For camera modules: Reference official camera module specifications and programming guides
- Source hardware-specific examples from manufacturer repositories and technical documentation

## Common Issues

1. **Camera Busy Error**: Kill existing camera processes with `pkill -f main_camera`
2. **Import Errors**: Use `uv run` instead of direct Python execution
3. **Permission Issues**: Ensure user is in camera/video groups
