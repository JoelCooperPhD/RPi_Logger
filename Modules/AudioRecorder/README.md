# Audio Recorder Module

Multi-microphone audio recording system for Raspberry Pi with real-time device monitoring and USB hot-plug support.

## Features

- **Multi-device recording**: Record from multiple USB audio devices simultaneously with independent streams
- **Hot-plug support**: Automatic detection and handling of USB audio device connections/disconnections
- **Auto-selection**: Newly detected devices are automatically selected for recording (configurable)
- **Auto-recording**: Optional automatic recording start when devices are attached
- **Device removal handling**: Automatically stops recording and removes disconnected devices
- **Real-time monitoring**: Live feedback with recording duration and active device count
- **Async architecture**: High-performance async/await implementation with sounddevice
- **Session management**: Organized output with timestamped experiment folders
- **Interactive controls**: Keyboard shortcuts for device selection and recording control
- **Concurrent file I/O**: Asynchronous file saving with thread pool executors for optimal performance

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

**Auto-Recording Mode** (starts recording automatically when devices are detected):
```bash
uv run main_audio.py --auto-record-on-attach
```

**Manual Device Selection** (disable auto-selection of new devices):
```bash
uv run main_audio.py --no-auto-select-new
```

## Interactive Controls

When running in interactive mode:

- `[r]` - Start/Stop recording from selected devices
- `[1-9]` - Toggle device selection (by device ID 1-9)
- `[s]` - Refresh and show current device selection status
- `[q]` - Quit program (stops recording if active)
- `[Ctrl+C]` - Force quit

**Recording Feedback:**
- Real-time duration display while recording
- Status updates every ~2 seconds showing active device count
- Automatic device busy/error notifications

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
- **Default Sample Rate**: 48 kHz (configurable)
- **Block Size**: 1024 samples per callback
- **Architecture**: Asyncio-based with sounddevice library
- **Device Detection**: Uses `/proc/asound/cards` for ultra-fast USB detection (~5ms polling)
- **Concurrency**: Thread pool executors for audio processing and file I/O, async event loop for device management
- **Auto-Selection**: First newly detected device is automatically selected when enabled (default)
- **Device Removal**: Automatically deselects removed devices and stops recording to maintain data consistency
- **Recording Feedback**: Asynchronous queue-based status updates with ~2-second intervals

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
