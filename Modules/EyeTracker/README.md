# Eye Tracker Module

Professional eye tracking video recorder using Pupil Labs Neon device with master-slave architecture, real-time preview, and programmatic control.

## Features

🎯 **Real-time Gaze Tracking**: Live gaze fixation overlay with device status indication
📹 **High-Quality Recording**: FFmpeg-based H.264 video encoding with gaze overlay
🔄 **Master-Slave Architecture**: Command-driven operation via JSON protocol
🖱️ **Interactive Controls**: Standalone mode with keyboard shortcuts (q=quit, s=snapshot, r=record)
⚡ **Smooth Performance**: Async frame writing to prevent visualization stuttering
⚙️ **Flexible Configuration**: Multiple resolutions, frame rates, and output options
📸 **Snapshot Capability**: Single-frame capture with gaze overlay and metadata
🛡️ **Signal Handling**: Graceful shutdown with proper resource cleanup

## Requirements

- **Pupil Labs Neon device** on same network
- **Python packages**: `pupil-labs-realtime-api`, `opencv-python`, `numpy`
- **FFmpeg** installed on system
- **Operating System**: Linux (tested on Raspberry Pi 5)

## Quick Start

### Standalone Mode (Interactive)

```bash
# Start eye tracker with default settings
uv run fixation_recorder.py

# High resolution at 30fps
uv run fixation_recorder.py --resolution 1920x1080 --fps 30

# Low resolution for better performance
uv run fixation_recorder.py -r 1280x720 -f 15 --preset ultrafast

# Custom output directory
uv run fixation_recorder.py --output recordings
```

### Slave Mode (Programmatic Control)

```bash
# Start in slave mode for master control
uv run fixation_recorder_v2.py --slave --output recordings
```

## Usage Modes

### Version Comparison

| Feature | fixation_recorder.py | fixation_recorder_v2.py |
|---------|---------------------|-------------------------|
| Standalone Mode | ✅ Interactive preview | ✅ Interactive preview |
| Slave Mode | ❌ Not available | ✅ JSON command protocol |
| Master Integration | ❌ Not available | ✅ Full compatibility |
| Signal Handling | ✅ Basic | ✅ Advanced with status |
| Logging | ✅ Basic | ✅ Structured (stderr) |

### Standalone Mode Controls

- **`q`**: Quit application
- **`s`**: Take snapshot with gaze overlay
- **`r`**: Toggle recording on/off
- **Close Window**: Graceful shutdown

### Slave Mode Commands

Send JSON commands via stdin when running in `--slave` mode:

```json
{"command": "start_recording"}
{"command": "stop_recording"}
{"command": "take_snapshot"}
{"command": "get_status"}
{"command": "quit"}
```

## Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--resolution` | 1600x1200 | Recording resolution (WIDTHxHEIGHT) |
| `--fps` | 20 | Recording framerate |
| `--preview-width` | 480 | Preview window width in pixels |
| `--timeout` | 10 | Device discovery timeout in seconds |
| `--preset` | ultrafast | FFmpeg encoding preset |
| `--output` | eye_tracking_data | Output directory for files |
| `--slave` | False | Run in slave mode (no GUI) |

### FFmpeg Presets
- **ultrafast**: Best real-time performance (recommended for Raspberry Pi)
- **superfast, veryfast, faster**: Balanced performance/quality
- **fast, medium**: Higher quality, more CPU intensive

## File Structure

```
EyeTracker/
├── fixation_recorder.py        # Standalone eye tracking recorder
├── fixation_recorder_v2.py     # Master-slave compatible recorder
├── README.md                   # This documentation
└── eye_tracking_data/          # Output directory (auto-created)
    ├── gaze_video_*.mp4        # Video recordings with overlays
    └── gaze_snapshot_*.jpg     # Snapshot images
```

## Architecture

### Standalone Mode
- Real-time preview window with gaze overlay
- Interactive keyboard controls
- Direct device control with immediate feedback
- Ideal for testing and manual operation

### Slave Mode (v2 only)
- No GUI interface (headless operation)
- JSON command protocol via stdin/stdout
- Status reporting to master process
- Integrates with larger RPi_Logger ecosystem
- Signal handling for graceful shutdown

## Master Integration

Eye tracker v2 is designed to integrate seamlessly with the RPi_Logger camera system:

```python
import subprocess
import json

# Start eye tracker in slave mode
proc = subprocess.Popen(
    ["uv", "run", "fixation_recorder_v2.py", "--slave"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True
)

# Send commands
proc.stdin.write(json.dumps({"command": "start_recording"}) + "\n")
proc.stdin.flush()

# Read status
status = json.loads(proc.stdout.readline())
print(f"Status: {status}")

# Cleanup
proc.stdin.write(json.dumps({"command": "quit"}) + "\n")
proc.wait()
```

## Output Files

### Video Recordings
```
eye_tracking_data/gaze_video_[resolution]_[fps]fps_[timestamp].mp4
```

### Snapshots
```
eye_tracking_data/gaze_snapshot_[timestamp].jpg
```

## Performance Features

- **Async frame writing** - Video encoding happens in background thread for smooth preview
- **Buffer monitoring** - Automatic frame dropping to maintain real-time performance
- **Device status overlay** - Red circle when worn, yellow when not worn
- **Timestamp overlays** - Frame numbers and Unix timestamps embedded
- **Optimized for Raspberry Pi** - Non-blocking IO prevents visualization stuttering

## Performance Notes

- For Raspberry Pi, use lower resolutions (1280x720 or below) and 'ultrafast' preset
- Frame rate depends on network speed and processing power
- Buffer size: 30 frames (adjustable in code)
- Effective frame rate ~20-25 FPS on Pi 5 with dual cameras running

## Troubleshooting

### Common Issues

1. **Device not found**: Ensure Neon device is on same network and powered on
2. **Slow performance**: Reduce resolution or framerate, use 'ultrafast' preset
3. **FFmpeg errors**: Ensure FFmpeg is installed: `sudo apt-get install ffmpeg`
4. **Resource conflicts**: Only one instance can access the device at a time
5. **Process hanging**: Use `pkill -f fixation_recorder` to kill stuck processes

### Hardware Setup

1. Connect Pupil Labs Neon to same network as Raspberry Pi
2. Ensure adequate network bandwidth for real-time streaming
3. Use fast storage for recording (USB 3.0 recommended)
4. Verify device connectivity before starting recording

## Integration Examples

### With Camera System

```bash
# Start both camera and eye tracker in slave mode
uv run ../Cameras/camera_module.py --slave --output recordings &
uv run fixation_recorder_v2.py --slave --output recordings &

# Control both via master program
python master_control.py
```

### Status Monitoring

The slave mode provides detailed status information:

```json
{
  "type": "status",
  "status": "status_report",
  "timestamp": "2025-01-15T10:30:45.123456",
  "data": {
    "recording": true,
    "frame_count": 1250,
    "output_file": "recordings/gaze_video_1600x1200_20fps_20250115_103045.mp4",
    "device_connected": true
  }
}
```

## Support

For issues and questions, refer to the main project documentation in `/CLAUDE.md`.