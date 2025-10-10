# Audio Recorder Usage Guide

Detailed usage examples and advanced configuration for the Audio Recorder module.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Interactive Controls](#interactive-controls)
3. [Advanced Configuration](#advanced-configuration)
4. [Device Management](#device-management)
5. [Troubleshooting](#troubleshooting)

## Quick Start

### Basic Recording Session

Start the recorder in interactive mode:
```bash
cd /home/rs-pi-2/Development/RPi_Logger/Modules/AudioRecorder
uv run python3 main_audio.py
```

### Custom Output Directory

```bash
uv run python3 main_audio.py --output-dir ~/my_recordings/session1
```

### High-Quality Recording

```bash
uv run python3 main_audio.py --sample-rate 96000 --session-prefix high_quality
```

## Interactive Controls

Once running, use these keyboard controls:

| Key | Action |
|-----|--------|
| `r` | Toggle recording (start/stop) |
| `1-9` | Toggle device selection for device ID |
| `s` | Refresh and show device list |
| `q` | Quit the program |
| `Ctrl+C` | Force quit |

### Workflow Example

1. Start the program: `uv run python3 main_audio.py`
2. Wait for devices to be detected (auto-selected if enabled)
3. Press `s` to see available devices
4. Press `2` to select/deselect device ID 2
5. Press `r` to start recording
6. Press `r` again to stop and save recordings

## Advanced Configuration

### Auto-Start Recording

Automatically start recording when devices are detected:
```bash
uv run python3 main_audio.py --auto-record-on-attach
```

### Disable Auto-Selection

Manually select devices instead of auto-selection:
```bash
uv run python3 main_audio.py --no-auto-select-new
```

### Custom Session Naming

```bash
uv run python3 main_audio.py --session-prefix my_experiment
# Creates: my_experiment_20251010_083000/
```

### Logging Configuration

Enable debug logging:
```bash
uv run python3 main_audio.py --log-level debug
```

Save logs to file:
```bash
uv run python3 main_audio.py --log-level info --log-file audio_session.log
```

## Device Management

### Listing Available Devices

Use the system tool to list audio devices:
```bash
arecord -l
```

Example output:
```
card 2: Device [USB Audio Device], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
```

### USB Hot-Plug Support

The recorder automatically detects:
- Device connections (plugging in USB mics)
- Device disconnections (unplugging USB mics)

When auto-select is enabled (default), newly connected devices are automatically selected for recording.

### Multiple Device Recording

To record from multiple devices simultaneously:
1. Connect all USB microphones
2. Start the program
3. Use keys `1-9` to toggle selection for each device
4. Press `r` to start recording from all selected devices

Each device records to a separate WAV file.

## Troubleshooting

### No Devices Detected

**Problem**: Program shows "No input devices found!"

**Solutions**:
1. Check USB connections:
   ```bash
   arecord -l
   ```
2. Verify user permissions:
   ```bash
   groups $USER
   # Should include 'audio'
   ```
3. Add to audio group if needed:
   ```bash
   sudo usermod -a -G audio $USER
   # Log out and back in
   ```

### Device Busy Error

**Problem**: Cannot start recording, device reports as busy

**Solutions**:
1. Kill existing processes:
   ```bash
   pkill -f main_audio
   pkill -f audio_monitor
   ```
2. Check for other audio applications:
   ```bash
   lsof /dev/snd/*
   ```

### Recording Quality Issues

**Problem**: Audio sounds distorted or has dropouts

**Solutions**:
1. Lower sample rate:
   ```bash
   uv run python3 main_audio.py --sample-rate 44100
   ```
2. Check CPU usage:
   ```bash
   top
   ```
3. Reduce number of simultaneous recordings
4. Ensure adequate cooling for Raspberry Pi

### Import Errors

**Problem**: `ModuleNotFoundError` when running

**Solutions**:
1. Always use `uv run`:
   ```bash
   uv run python3 main_audio.py
   ```
2. Sync dependencies:
   ```bash
   cd /home/rs-pi-2/Development/RPi_Logger
   uv sync
   ```

### Permission Denied

**Problem**: Cannot write to output directory

**Solutions**:
1. Check directory permissions:
   ```bash
   ls -la recordings/
   ```
2. Create with proper permissions:
   ```bash
   mkdir -p recordings/audio
   chmod 755 recordings/audio
   ```

## Output Files

### File Naming Convention

```
mic{ID}_{DeviceName}_rec{Number}_{Timestamp}.wav
```

Example:
```
mic2_USB_Audio_Device_rec001_083045.wav
mic5_Blue_Microphones_rec002_084120.wav
```

### Directory Structure

```
recordings/audio/
└── experiment_20251010_083000/
    ├── mic2_USB_Audio_Device_rec001_083045.wav
    ├── mic2_USB_Audio_Device_rec002_084120.wav
    └── mic5_Blue_Microphones_rec001_083045.wav
```

## Performance Tips

1. **CPU Usage**: Recording multiple high-sample-rate devices can be CPU-intensive
2. **Storage**: 48kHz mono recording uses ~5.8 MB per minute per device
3. **USB Bandwidth**: Multiple USB audio devices on same hub may cause issues
4. **Cooling**: Ensure adequate cooling for Raspberry Pi during long sessions

## Integration Examples

### With Other Modules

Recording synchronized with camera capture:
```bash
# Terminal 1: Start audio recorder
cd Modules/AudioRecorder
uv run python3 main_audio.py --session-prefix sync_test

# Terminal 2: Start camera system
cd Modules/Cameras
uv run python3 main_camera.py
```

### Scripted Recording

For automated/batch recording, see `examples/audio_monitor_fast.py`

## References

- Main documentation: [README.md](../README.md)
- Project overview: [CLAUDE.md](/home/rs-pi-2/Development/RPi_Logger/CLAUDE.md)
- Related modules: `../Cameras/`, `../EyeTracker/`
