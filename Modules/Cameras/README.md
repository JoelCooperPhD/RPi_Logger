# Camera Module Documentation

A comprehensive camera module for Raspberry Pi systems with real-time preview, timestamp overlays, and flexible control options.

## Features

🎥 **Real-time Preview**: Live video feed with timestamp overlays and recording indicators
📹 **High-Quality Recording**: H.264 video encoding with configurable resolution and frame rate
⏰ **Timestamp Overlays**: Automatic timestamp embedding in both preview and recorded video
🖱️ **Interactive Controls**: Keyboard shortcuts (q=quit, s=snapshot) and window close detection
🔄 **IPC Support**: Subprocess communication via JSON commands
⚙️ **Flexible Configuration**: Headless mode, custom resolutions, frame rates
📸 **Still Image Capture**: High-resolution snapshot capability
🛡️ **Robust Error Handling**: Comprehensive cleanup and error recovery

## Hardware Compatibility

- **Raspberry Pi Models**: Pi 4, Pi 5, and compatible boards
- **Camera Modules**: All official Raspberry Pi cameras (V1, V2, V3, HQ, Global Shutter)
- **USB Cameras**: Limited support via libcamera
- **Operating System**: Raspberry Pi OS Bullseye or later

## Quick Start

### Basic Recording with Preview (Default)
```bash
# Record with live preview until 'q' is pressed
python camera_module.py

# Record for 30 seconds with preview
python camera_module.py --duration 30
```

### Headless Recording
```bash
# Record without preview window
python camera_module.py --duration 30 --no-preview
```

### High-Resolution Recording
```bash
# 4K recording at 24fps
python camera_module.py --resolution 3840x2160 --fps 24 --duration 60
```

## Installation

### Requirements
```bash
# Install dependencies
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-numpy

# Or using pip/uv
pip install picamera2 opencv-python numpy
```

### Verify Installation
```bash
# Test camera connection
python camera_module.py --duration 3 --no-preview
```

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--resolution` | `1920x1080` | Video resolution (e.g., 1280x720, 3840x2160) |
| `--fps` | `30` | Frames per second (10-60) |
| `--save-location` | `./recordings` | Directory for saved files |
| `--camera-id` | `0` | Camera index (0 or 1 for Pi 5) |
| `--duration` | `None` | Recording duration in seconds (None for manual) |
| `--no-preview` | `False` | Disable preview window (headless mode) |
| `--ipc` | `False` | Run in IPC mode for subprocess communication |

## Interactive Controls

When preview is enabled:
- **Q**: Quit recording and exit
- **S**: Take snapshot (saved as .jpg)
- **X button**: Close window and terminate gracefully

## Programming Interface

### Basic Usage
```python
import asyncio
from camera_module import CameraModule

async def record_video():
    camera = CameraModule(
        resolution=(1920, 1080),
        fps=30,
        save_location="./my_recordings"
    )

    try:
        await camera.initialize_camera()
        await camera.start_camera()

        # Start recording
        recording_path = await camera.start_recording("my_video.h264")

        # Record for 10 seconds
        await asyncio.sleep(10)

        # Stop recording
        await camera.stop_recording()

    finally:
        await camera.cleanup()

# Run the recording
asyncio.run(record_video())
```

### IPC Mode (Subprocess Control)
```python
import subprocess
import json

# Start camera in IPC mode
proc = subprocess.Popen([
    "python", "camera_module.py", "--ipc"
], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

# Send commands
commands = [
    {"action": "start_recording", "params": {"filename": "test.h264"}},
    {"action": "capture_image", "params": {"filename": "snapshot.jpg"}},
    {"action": "stop_recording"},
    {"action": "shutdown"}
]

for cmd in commands:
    proc.stdin.write(json.dumps(cmd) + '\\n')
    proc.stdin.flush()

    response = json.loads(proc.stdout.readline())
    print(f"Response: {response}")
```

### Available IPC Commands

| Command | Parameters | Description |
|---------|------------|-------------|
| `get_status` | None | Get camera status and configuration |
| `start_recording` | `filename` (optional) | Start video recording |
| `stop_recording` | None | Stop current recording |
| `capture_image` | `filename` (optional) | Take still image |
| `set_controls` | Camera controls dict | Adjust camera settings |
| `shutdown` | None | Gracefully shutdown camera |

## Configuration Examples

### Low Latency Setup
```python
camera = CameraModule(
    resolution=(640, 480),
    fps=60,
    show_preview=True
)
```

### Security Camera Setup
```python
camera = CameraModule(
    resolution=(1920, 1080),
    fps=15,
    save_location="/media/storage/recordings",
    show_preview=False
)
```

### Time-lapse Setup
```python
# Take photos at intervals
camera = CameraModule(resolution=(3840, 2160), show_preview=False)
await camera.initialize_camera()
await camera.start_camera()

for i in range(100):
    await camera.capture_image(f"timelapse_{i:04d}.jpg")
    await asyncio.sleep(60)  # One photo per minute
```

## File Formats and Quality

### Video Recording
- **Format**: H.264 (.h264 files)
- **Quality**: High quality encoding (10 Mbps bitrate)
- **Compatibility**: Can be converted to MP4 using ffmpeg

### Still Images
- **Format**: JPEG (.jpg files)
- **Quality**: Full sensor resolution
- **Metadata**: EXIF data included

### Converting H.264 to MP4
```bash
# Using ffmpeg
ffmpeg -i recording_20231201_143022.h264 -c copy output.mp4

# Batch convert all recordings
for f in *.h264; do ffmpeg -i "$f" -c copy "${f%.h264}.mp4"; done
```

## Performance Optimization

### For High Frame Rates
- Use lower resolutions (1280x720 or below)
- Disable preview for headless operation
- Ensure sufficient storage speed (Class 10 SD card minimum)

### For High Resolutions
- Use lower frame rates (15-24fps)
- Ensure adequate cooling for Raspberry Pi
- Monitor CPU temperature during recording

### Memory Usage
- Higher resolutions use more memory
- Consider buffer_count in configuration
- Monitor system resources during operation

## Troubleshooting

### Common Issues

**Camera not detected**
```bash
# Check camera connection
libcamera-hello --list-cameras

# Check permissions
sudo usermod -a -G video $USER
# Logout and login again
```

**Preview window not showing**
```bash
# Check display environment
echo $DISPLAY

# For SSH users, enable X11 forwarding
ssh -X pi@raspberry-pi-ip
```

**Recording files empty or corrupted**
```bash
# Check storage space
df -h

# Check write permissions
ls -la recordings/

# Test with shorter duration
python camera_module.py --duration 5 --no-preview
```

**High CPU usage**
- Lower resolution or frame rate
- Disable preview for headless operation
- Check system temperature

### Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `Camera __init__ sequence did not complete` | Camera in use by another process | Kill other camera processes |
| `Unable to set controls: Device or resource busy` | Multiple camera access | Ensure only one camera instance |
| `Failed to add timestamp overlay` | OpenCV/array issues | Check numpy/opencv installation |
| `Preview window destroyed` | User closed window | Normal termination behavior |

## Testing

Run the comprehensive test suite:
```bash
# Run all tests
python test_camera_comprehensive.py

# Run specific test categories
python -m unittest test_camera_comprehensive.TestCameraModule
python -m unittest test_camera_comprehensive.TestCameraIntegration
python -m unittest test_camera_comprehensive.TestCameraStress
```

## Examples

Explore various usage patterns:
```bash
# Run interactive examples
python camera_examples.py

# Or run specific examples directly
python -c "import asyncio; from camera_examples import example_basic_recording; asyncio.run(example_basic_recording())"
```

## Integration with Other Systems

### Motion Detection
```python
# Framework for motion detection
import cv2

async def motion_detection_loop():
    camera = CameraModule(resolution=(640, 480), show_preview=False)
    await camera.initialize_camera()
    await camera.start_camera()

    prev_frame = None

    while True:
        frame = camera.picam2.capture_array("main")
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        if prev_frame is not None:
            diff = cv2.absdiff(prev_frame, gray)
            if cv2.countNonZero(diff) > threshold:
                # Motion detected - start recording
                await camera.start_recording()

        prev_frame = gray
        await asyncio.sleep(0.1)
```

### Web Streaming
```python
# Basic framework for web streaming
from flask import Flask, Response
import cv2

app = Flask(__name__)
camera = CameraModule(show_preview=False)

def generate_frames():
    while True:
        frame = camera.picam2.capture_array("main")
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\\r\\n'
               b'Content-Type: image/jpeg\\r\\n\\r\\n' + frame + b'\\r\\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')
```

## License and Support

This module is part of the RPi_Logger project. For issues, feature requests, or contributions, please refer to the main project repository.

### Version History
- **v1.0**: Initial release with basic recording
- **v1.1**: Added preview functionality and IPC support
- **v1.2**: Enhanced error handling and window close detection
- **v1.3**: Comprehensive testing and documentation

---

For more examples and advanced usage, see `camera_examples.py` and `test_camera_comprehensive.py`.