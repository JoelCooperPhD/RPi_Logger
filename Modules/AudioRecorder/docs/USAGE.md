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

**Behavior:**
- When enabled, recording starts automatically after a device is selected
- Works in combination with auto-selection (enabled by default)
- Useful for unattended/automated recording sessions
- If a selected device is removed, recording stops to maintain data consistency

### Disable Auto-Selection

Manually select devices instead of auto-selection:
```bash
uv run python3 main_audio.py --no-auto-select-new
```

**Behavior:**
- Newly detected devices will NOT be automatically selected
- You must manually select devices using keyboard controls (1-9)
- Useful when you want precise control over which devices record
- Existing selected devices remain selected across device hot-plug events

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

The recorder automatically detects and handles:
- **Device connections** (plugging in USB mics)
  - Detected via `/proc/asound/cards` monitoring (~5ms polling interval)
  - Newly detected devices are automatically selected (if auto-select enabled)
  - Device list refreshes and displays immediately
  - Can optionally auto-start recording with `--auto-record-on-attach`

- **Device disconnections** (unplugging USB mics)
  - Removed devices are automatically deselected from recording
  - If recording is active, it stops immediately to maintain data consistency
  - Prevents partial/corrupted recordings from interrupted devices
  - Status displayed showing which device was removed

### Multiple Device Recording

To record from multiple devices simultaneously:
1. Connect all USB microphones
2. Start the program
3. Use keys `1-9` to toggle selection for each device
4. Press `r` to start recording from all selected devices

**Recording Behavior:**
- Each device records to a separate WAV file with independent audio stream
- All recordings are synchronized to the same start time
- Files are saved concurrently using async I/O for optimal performance
- Recording feedback shows total duration and active device count
- Status updates appear every ~2 seconds during recording

**File Naming:**
Each device produces files named: `mic{ID}_{DeviceName}_rec{Number}_{Timestamp}.wav`

Example with 2 devices:
```
mic2_USB_Audio_Device_rec001_151702.wav
mic5_Blue_Microphones_rec001_151702.wav
```

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
   - Default 48kHz with 1024 block size provides good balance
   - Async architecture with thread pool executors minimizes overhead
   - Monitor CPU with `top` or `htop` during multi-device recording

2. **Storage**: 48kHz mono recording uses ~5.8 MB per minute per device
   - 16-bit PCM format provides good quality-to-size ratio
   - Ensure adequate free space in output directory
   - Use `df -h` to check available storage

3. **USB Bandwidth**: Multiple USB audio devices on same hub may cause issues
   - Distribute devices across different USB controllers if possible
   - USB 3.0 ports recommended for multiple high-quality devices
   - Watch for status error messages indicating buffer underruns

4. **Cooling**: Ensure adequate cooling for Raspberry Pi during long sessions
   - Heatsinks and/or fans recommended for extended recording
   - Monitor temperature: `vcgencmd measure_temp`

5. **Polling Interval**: Device detection uses 5ms polling by default
   - Fast enough for immediate detection without excessive CPU usage
   - Configurable in code (line 411) if needed for specific use cases

## Advanced Features

### Recording Feedback System

The audio recorder provides real-time status updates during recording:

**Status Messages:**
- `[REC] Started recording #N on M devices` - Recording initiated
- `[REC] Recording... Ns (M devices)` - Live progress (updates every ~2s)
- `[SAVE] Device N: filename.wav` - Per-device save confirmation
- `[SAVE] All recordings saved (Ns)` - Recording completed with total duration
- `[ERROR] Device Name: error message` - Stream errors or device issues

**Implementation Details:**
- Uses async queue for non-blocking feedback (main_audio.py:88, 265-282)
- Audio callbacks queue feedback every ~2 seconds (main_audio.py:162-167)
- Error notifications are queued immediately (main_audio.py:169-173)
- Queue processing runs in main event loop without blocking I/O

### Asynchronous File Saving

Files are saved using concurrent async I/O for optimal performance:
- Audio data processing runs in thread pool executor (main_audio.py:239-246)
- WAV file writing runs in separate thread pool (main_audio.py:253-261)
- Multiple device files save concurrently via `asyncio.gather()` (main_audio.py:224)
- Main event loop remains responsive during save operations

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
