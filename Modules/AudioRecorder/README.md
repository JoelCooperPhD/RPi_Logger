# Audio Recorder Module

Multi-microphone audio recording system for Raspberry Pi with real-time device monitoring and USB hot-plug support.

## Features

- **Multi-device recording**: Record from multiple USB audio devices simultaneously
- **Hot-plug support**: Automatic detection of USB audio device connections/disconnections
- **Real-time monitoring**: Live feedback during recording sessions
- **Async architecture**: High-performance async/await implementation with sounddevice
- **Session management**: Organized output with timestamped experiment folders
- **Interactive controls**: Keyboard shortcuts for device selection and recording control

## Quick Start

### Installation

This module uses `uv` for package management. From the project root:

```bash
uv sync
```

### Basic Usage

**Interactive Mode** (default):
```bash
uv run main_audio.py
```

**With Custom Settings**:
```bash
uv run main_audio.py --output-dir recordings/my_session --sample-rate 48000
```

## Controls

When running in interactive mode:

- `[r]` - Start/Stop recording from selected devices
- `[1-9]` - Toggle device selection (by device ID)
- `[s]` - Show device selection status
- `[q]` - Quit program
- `[Ctrl+C]` - Force quit

## Command-Line Options

```bash
uv run main_audio.py --help
```

Key arguments:
- `--output-dir` - Output directory for recordings (default: `recordings/audio`)
- `--sample-rate` - Sample rate in Hz (default: 48000)
- `--session-prefix` - Prefix for experiment folders (default: "experiment")
- `--auto-record-on-attach` - Auto-start recording when devices are detected
- `--no-auto-select-new` - Disable automatic selection of new devices
- `--log-level` - Logging level (DEBUG, INFO, WARNING, ERROR)
- `--log-file` - Log file path (optional)

## File Structure

```
AudioRecorder/
├── main_audio.py           # Main multi-microphone recorder
├── README.md               # This file
├── examples/               # Example scripts and compatibility shims
│   └── audio_monitor_fast.py
├── docs/                   # Additional documentation
└── data/                   # Default recordings output (auto-created)
```

## Output Format

Recordings are saved in timestamped experiment folders:

```
recordings/audio/
└── experiment_20250925_151702/
    ├── mic2_USB_Audio_Device_rec001_151702.wav
    └── mic5_Blue_Microphones_rec001_151702.wav
```

Files are named: `mic{ID}_{DeviceName}_rec{Number}_{Timestamp}.wav`

## Technical Details

- **Audio Format**: 16-bit PCM WAV, mono per device
- **Default Sample Rate**: 48 kHz
- **Architecture**: Asyncio-based with sounddevice library
- **Device Detection**: Uses `/proc/asound/cards` for fast USB detection
- **Concurrency**: Thread pool for I/O operations, async for device management

## Dependencies

Core dependencies (managed by uv):
- `sounddevice` - Audio I/O
- `numpy` - Audio data processing
- `aiofiles` - Async file operations
- `cli_utils` - Shared CLI utilities (from parent project)

## Examples

See `examples/` directory for:
- `audio_monitor_fast.py` - Compatibility shim for legacy code

## Troubleshooting

**No devices detected:**
- Check USB connections
- Verify devices appear in `arecord -l`
- Ensure user has audio permissions (add to `audio` group)

**Recording fails to start:**
- Kill any existing audio processes: `pkill -f main_audio`
- Check device isn't locked by another application
- Verify sample rate compatibility with your hardware

**Import errors:**
- Always use `uv run` instead of direct Python execution
- Ensure you've run `uv sync` to install dependencies

## Related Modules

- `../Cameras/` - Camera recording module with similar architecture
- `../EyeTracker/` - Eye tracking module
- `../../cli_utils.py` - Shared CLI argument parsing and utilities

## License

Part of the RPi_Logger project.
