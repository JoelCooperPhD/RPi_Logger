# Picamera2 Comprehensive Reference Guide

## Table of Contents
1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Basic Operations](#basic-operations)
4. [Camera Configuration](#camera-configuration)
5. [Camera Controls and Properties](#camera-controls-and-properties)
6. [Image Capture](#image-capture)
7. [Video Recording](#video-recording)
8. [Preview Windows](#preview-windows)
9. [Advanced Topics](#advanced-topics)
10. [Application Notes](#application-notes)
11. [Parameter Reference](#parameter-reference)
12. [Code Examples](#code-examples)

---

## Introduction

Picamera2 is a Python library for controlling cameras on Raspberry Pi systems. It's built on the libcamera project and is the successor to the legacy PiCamera library.

**Key Features:**
- Modern camera interface using libcamera
- Support for multiple camera streams (main, lores, raw)
- Hardware-accelerated preview windows
- Video encoding and streaming
- Synchronization between multiple cameras
- Flexible configuration system

**Requirements:**
- Raspberry Pi OS Bullseye or later
- Camera connected via ribbon cable (limited USB support available)
- Compatible with all Raspberry Pi camera modules

---

## Getting Started

### Installation

Picamera2 is pre-installed on recent Raspberry Pi OS images. For manual installation:

```bash
# Full installation
sudo apt install -y python3-picamera2

# Lite installation (reduced GUI components)
sudo apt install -y python3-picamera2 --no-install-recommends
```

### First Example

```python
from picamera2 import Picamera2, Preview
import time

picam2 = Picamera2()
camera_config = picam2.create_preview_configuration()
picam2.configure(camera_config)
picam2.start_preview(Preview.QTGL)  # or Preview.DRM for headless
picam2.start()
time.sleep(2)
picam2.capture_file("test.jpg")
picam2.stop()
```

### High-Level API (Simple Usage)

```python
from picamera2 import Picamera2

# Simple image capture
picam2 = Picamera2()
picam2.start_and_capture_file("test.jpg")

# Simple video recording (5 seconds)
picam2.start_and_record_video("test.mp4", duration=5)
```

---

## Basic Operations

### Camera Lifecycle

1. **Create** Picamera2 object
2. **Configure** camera with desired settings
3. **Start** the camera
4. **Capture** images/video
5. **Stop** the camera

```python
from picamera2 import Picamera2

# Step 1: Create
picam2 = Picamera2()

# Step 2: Configure
config = picam2.create_preview_configuration()
picam2.configure(config)

# Step 3: Start
picam2.start()

# Step 4: Capture (various methods)
array = picam2.capture_array()
image = picam2.capture_image()
picam2.capture_file("image.jpg")

# Step 5: Stop
picam2.stop()
```

### Multiple Cameras

```python
from picamera2 import Picamera2

# Check available cameras
cameras = Picamera2.global_camera_info()
print(cameras)

# Use multiple cameras
picam2a = Picamera2(0)
picam2b = Picamera2(1)

picam2a.start()
picam2b.start()

picam2a.capture_file("cam0.jpg")
picam2b.capture_file("cam1.jpg")
```

---

## Camera Configuration

### Configuration Types

Picamera2 provides three main configuration generators:

```python
# Preview configuration - optimized for display and preview
preview_config = picam2.create_preview_configuration()

# Still configuration - optimized for high-quality captures
still_config = picam2.create_still_configuration()

# Video configuration - optimized for video recording
video_config = picam2.create_video_configuration()
```

### Stream Configuration

Cameras can produce up to three streams simultaneously:

- **Main stream**: Primary output (always available)
- **Lores stream**: Lower resolution output (optional)
- **Raw stream**: Unprocessed sensor data (optional)

```python
# Configure multiple streams
config = picam2.create_preview_configuration(
    main={"size": (1920, 1080), "format": "RGB888"},
    lores={"size": (640, 480), "format": "YUV420"},
    raw={"format": "SBGGR12"}
)
picam2.configure(config)
```

### General Configuration Parameters

```python
config = picam2.create_preview_configuration(
    # Transform (rotation/mirroring)
    transform=Transform(hflip=True, vflip=False),

    # Color space
    colour_space=ColorSpace.Sycc(),

    # Buffer allocation
    buffer_count=4,

    # Which stream to display/encode
    display="main",
    encode="main",

    # Queue frames for faster capture
    queue=True,

    # Runtime controls
    controls={"ExposureTime": 10000, "AnalogueGain": 1.0}
)
```

### Sensor Configuration

```python
# Get available sensor modes
modes = picam2.sensor_modes
print(modes)

# Configure specific sensor mode
config = picam2.create_preview_configuration(
    sensor={'output_size': (1332, 990), 'bit_depth': 10}
)
```

### Stream Formats and Sizes

#### Main Stream Formats
- **XBGR8888**: 32-bit RGB with alpha (recommended for Qt preview)
- **RGB888**: 24-bit RGB (compatible with OpenCV)
- **BGR888**: 24-bit BGR (compatible with OpenCV)
- **YUV420**: 12-bit YUV (memory efficient)

#### Example Configuration
```python
# High-quality RGB capture
config = picam2.create_still_configuration(
    main={"size": (4056, 3040), "format": "RGB888"}
)

# Memory-efficient YUV preview
config = picam2.create_preview_configuration(
    main={"size": (1920, 1080), "format": "YUV420"}
)
```

---

## Camera Controls and Properties

### Setting Controls

Controls can be set at three different times:

1. **In configuration** (applied before camera starts)
2. **Before starting** (applied on first frame)
3. **While running** (applied with frame delay)

```python
# Method 1: In configuration
config = picam2.create_preview_configuration(
    controls={"ExposureTime": 10000, "AnalogueGain": 1.0}
)

# Method 2: Before starting
picam2.configure(config)
picam2.set_controls({"ExposureTime": 10000, "AnalogueGain": 1.0})
picam2.start()

# Method 3: While running
picam2.start()
picam2.set_controls({"ExposureTime": 20000, "AnalogueGain": 2.0})
```

### Object-Style Control Syntax

```python
# Set controls using object syntax
picam2.controls.ExposureTime = 10000
picam2.controls.AnalogueGain = 1.0

# Atomic updates while running
with picam2.controls as controls:
    controls.ExposureTime = 15000
    controls.AnalogueGain = 1.5
```

### Autofocus Controls

```python
from libcamera import controls

# Continuous autofocus
picam2.set_controls({"AfMode": controls.AfModeEnum.Continuous})

# Manual focus to infinity
picam2.set_controls({
    "AfMode": controls.AfModeEnum.Manual,
    "LensPosition": 0.0
})

# Trigger autofocus cycle
success = picam2.autofocus_cycle()

# Non-blocking autofocus
job = picam2.autofocus_cycle(wait=False)
# Do other work...
success = picam2.wait(job)
```

### Key Camera Controls

| Control | Description | Values |
|---------|-------------|--------|
| `ExposureTime` | Exposure time in microseconds | Sensor dependent |
| `AnalogueGain` | Sensor analog gain | Sensor dependent |
| `AwbEnable` | Auto white balance on/off | True/False |
| `AeEnable` | Auto exposure on/off | True/False |
| `Brightness` | Image brightness | -1.0 to 1.0 |
| `Contrast` | Image contrast | 0.0 to 32.0 |
| `Saturation` | Color saturation | 0.0 to 32.0 |
| `Sharpness` | Image sharpness | 0.0 to 16.0 |
| `ColourGains` | Manual white balance gains | (red_gain, blue_gain) |
| `ScalerCrop` | Digital zoom/crop | Rectangle(x, y, w, h) |

### Camera Properties (Read-Only)

```python
# Access camera properties
props = picam2.camera_properties
print(f"Model: {props['Model']}")
print(f"Rotation: {props['Rotation']}")
print(f"Pixel Array Size: {props['PixelArraySize']}")
```

---

## Image Capture

### Capture Methods

```python
# Capture as numpy array
array = picam2.capture_array("main")  # 3D array [height, width, channels]

# Capture as PIL image
image = picam2.capture_image("main")

# Capture to file
picam2.capture_file("image.jpg")  # Auto-detects format from extension

# Capture to buffer/memory
buffer = picam2.capture_buffer("main")  # 1D array

# Capture with metadata
metadata = picam2.capture_metadata()
```

### Multiple Stream Capture

```python
# Configure multiple streams
config = picam2.create_preview_configuration(
    main={"size": (1920, 1080)},
    lores={"size": (640, 480)}
)
picam2.configure(config)
picam2.start()

# Capture from multiple streams
arrays, metadata = picam2.capture_arrays(["main", "lores"])
main_array = arrays[0]
lores_array = arrays[1]
```

### Mode Switching and Capture

```python
# Fast preview with high-quality capture
preview_config = picam2.create_preview_configuration()
capture_config = picam2.create_still_configuration()

picam2.configure(preview_config)
picam2.start()

# Switch to capture mode, take photo, return to preview
array = picam2.switch_mode_and_capture_array(capture_config, "main")
picam2.switch_mode_and_capture_file(capture_config, "high_res.jpg")
```

### Request-Based Capture

```python
# Capture complete request (all streams + metadata)
request = picam2.capture_request()
main_array = request.make_array("main")
metadata = request.get_metadata()
request.release()  # IMPORTANT: Always release!

# Context manager (auto-release)
with picam2.captured_request() as request:
    array = request.make_array("main")
    request.save("main", "image.jpg")
```

### Timed Capture

```python
# Capture at specific time
import time
request = picam2.capture_request(flush=True)  # Ensure exposure starts after call
request = picam2.capture_request(flush=time.monotonic_ns())  # Specific timestamp
```

### Asynchronous Capture

```python
# Non-blocking capture
job = picam2.capture_file("image.jpg", wait=False)
# Do other work...
result = picam2.wait(job)

# With callback
def capture_done(job):
    print("Capture completed!")

job = picam2.capture_file("image.jpg", wait=False, signal_function=capture_done)
```

### Burst Capture

```python
# Fast burst capture
picam2.start_and_capture_files(
    "burst{:03d}.jpg",
    num_files=10,
    delay=0,  # No delay between captures
    initial_delay=0
)
```

---

## Video Recording

### Basic Video Recording

```python
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration())

encoder = H264Encoder(bitrate=10000000)
output = FileOutput("video.h264")

picam2.start_recording(encoder, output)
time.sleep(10)
picam2.stop_recording()
```

### Encoders

#### H264Encoder
```python
encoder = H264Encoder(
    bitrate=10000000,    # Bits per second
    repeat=False,        # Repeat headers for streaming
    iperiod=60          # I-frame interval
)
```

#### JpegEncoder (MJPEG)
```python
encoder = JpegEncoder(
    num_threads=4,       # Encoding threads
    q=75,               # JPEG quality (0-95)
    colour_subsampling=420  # YUV subsampling
)
```

#### MJPEGEncoder (Hardware)
```python
encoder = MJPEGEncoder(bitrate=10000000)
```

#### Quality Settings
```python
from picamera2.encoders import Quality

encoder = H264Encoder()
picam2.start_recording(encoder, "video.h264", quality=Quality.HIGH)
```

### Output Types

#### FileOutput
```python
from picamera2.outputs import FileOutput

# File output
output = FileOutput("video.h264")

# Memory buffer
import io
buffer = io.BytesIO()
output = FileOutput(buffer)

# Network socket
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.connect(("192.168.1.100", 12345))
output = FileOutput(sock.makefile("wb"))
```

#### FfmpegOutput
```python
from picamera2.outputs import FfmpegOutput

# MP4 with audio
output = FfmpegOutput("video.mp4", audio=True)

# HLS streaming
output = FfmpegOutput("-f hls -hls_time 4 -hls_list_size 5 stream.m3u8")

# UDP streaming
output = FfmpegOutput("-f mpegts udp://192.168.1.100:12345")
```

#### PyavOutput (Direct FFmpeg Library)
```python
from picamera2.outputs import PyavOutput

# MP4 output
output = PyavOutput("video.mp4")

# RTSP streaming
output = PyavOutput("rtsp://127.0.0.1:8554/stream", format="rtsp")

# UDP with custom format
output = PyavOutput("udp://192.168.1.100:12345", format="mpegts")
```

#### CircularOutput (Motion Detection)
```python
from picamera2.outputs import CircularOutput

# Circular buffer for 5 seconds at 30fps
output = CircularOutput(buffersize=150)
picam2.start_recording(encoder, output)

# When motion detected, start saving
output.fileoutput = "motion.h264"
output.start()
time.sleep(5)  # Record 5 seconds
output.stop()
```

### Audio Recording

```python
# With FfmpegOutput
output = FfmpegOutput("video.mp4", audio=True, audio_device="default")

# With PyavOutput
encoder = H264Encoder()
encoder.audio = True
output = PyavOutput("video.mp4")
```

### Multiple Outputs

```python
# Stream and record simultaneously
encoder = H264Encoder(repeat=True)
output1 = FfmpegOutput("-f mpegts udp://192.168.1.100:12345")  # Stream
output2 = FileOutput()  # Record

encoder.output = [output1, output2]
picam2.start_recording(encoder)

# Start/stop recording while streaming continues
output2.fileoutput = "recording.h264"
output2.start()
time.sleep(10)
output2.stop()
```

### Synchronized Multi-Camera Recording

```python
from libcamera import controls

# Server camera
picam2_server = Picamera2(0)
config = picam2_server.create_video_configuration(
    controls={'SyncMode': controls.rpi.SyncModeEnum.Server, 'FrameRate': 30}
)
encoder_server = H264Encoder()
encoder_server.sync_enable = True

picam2_server.start_recording(encoder_server, "server.h264")
encoder_server.sync.wait()  # Wait for synchronization

# Client camera (similar setup with Client mode)
```

---

## Preview Windows

### Preview Types

1. **QtGL Preview** (Hardware accelerated)
2. **DRM/KMS Preview** (Console/headless)
3. **Qt Preview** (Software rendered)
4. **NULL Preview** (No display)

```python
from picamera2 import Preview

# QtGL (recommended for GUI)
picam2.start_preview(Preview.QTGL, x=100, y=200, width=800, height=600)

# DRM for headless/console
picam2.start_preview(Preview.DRM)

# Qt for remote display/VNC
picam2.start_preview(Preview.QT)

# NULL (no display)
picam2.start_preview(Preview.NULL)  # or just start() without preview
```

### Preview Parameters

```python
from libcamera import Transform

picam2.start_preview(
    Preview.QTGL,
    x=100,           # X position
    y=200,           # Y position
    width=800,       # Width
    height=600,      # Height
    transform=Transform(hflip=1)  # Mirror horizontally
)
```

### Display Overlays

```python
import numpy as np

# Create RGBA overlay
overlay = np.zeros((300, 400, 4), dtype=np.uint8)
overlay[:150, 200:] = (255, 0, 0, 128)  # Semi-transparent red
overlay[150:, :200] = (0, 255, 0, 128)  # Semi-transparent green

picam2.set_overlay(overlay)
```

### Title Bar Information

```python
# Display metadata in title bar
picam2.title_fields = ["ExposureTime", "AnalogueGain", "ColourGains"]
```

---

## Advanced Topics

### Event Loop Callbacks

```python
from picamera2 import MappedArray
import cv2

def apply_timestamp(request):
    timestamp = time.strftime("%Y-%m-%d %X")
    with MappedArray(request, "main") as m:
        cv2.putText(m.array, timestamp, (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

# Apply to all frames before display/encoding
picam2.pre_callback = apply_timestamp

# Apply after capture but before display/encoding
picam2.post_callback = apply_timestamp
```

### Custom Function Dispatch

```python
def custom_capture_and_stop():
    def capture_stop_function():
        picam2.capture_file_("image.jpg", "main")
        picam2.stop_()
        return (True, None)

    functions = [
        lambda: picam2.switch_mode_(capture_config),
        capture_stop_function
    ]
    return picam2.dispatch_functions(functions, wait=True)
```

### Qt Integration

```python
from PyQt5.QtWidgets import QApplication
from picamera2.previews.qt import QGlPicamera2

app = QApplication([])
picam2 = Picamera2()
qpicamera2 = QGlPicamera2(picam2, width=800, height=600)

# Non-blocking operations
def capture_done(job):
    result = picam2.wait(job)
    print("Capture completed")

qpicamera2.done_signal.connect(capture_done)
picam2.switch_mode_and_capture_file(
    still_config, "image.jpg",
    signal_function=qpicamera2.signal_done
)
```

### Memory Management

```python
# YUV420 to RGB conversion (saves memory)
yuv420 = picam2.capture_array()
rgb = cv2.cvtColor(yuv420, cv2.COLOR_YUV420p2RGB)

# Increase CMA memory in /boot/config.txt
# dtoverlay=vc4-kms-v3d,cma-512

# Configure fewer buffers to save memory
config = picam2.create_still_configuration(buffer_count=1)
```

### Multi-Processing

```python
# Pass buffers between processes without copying
from picamera2.multiprocessing import Process, Pool

def process_frame(buffer, config):
    # Process in separate process
    array = make_array(buffer, config)
    # ... processing ...
    return result

# Use multiprocessing pool
with Pool() as pool:
    while True:
        buffer = picam2.capture_buffer()
        config = picam2.camera_configuration()["main"]
        result = pool.apply_async(process_frame, (buffer, config))
```

---

## Application Notes

### Network Streaming

#### Simple TCP Streaming
```python
import socket
from picamera2.encoders import H264Encoder

# Create socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind(("0.0.0.0", 8000))
sock.listen()
conn, addr = sock.accept()

# Stream H.264
encoder = H264Encoder(bitrate=10000000)
output = FileOutput(conn.makefile("wb"))
picam2.start_recording(encoder, output)
```

#### MJPEG Web Server
```python
from picamera2.outputs import FfmpegOutput

# Simple HTTP server streaming MJPEG
output = FfmpegOutput("-f mjpeg -")
# Serve via HTTP (see mjpeg_server.py example)
```

#### MediaMTX Integration
```python
# Stream to MediaMTX server
from picamera2.outputs import PyavOutput

output = PyavOutput("rtsp://127.0.0.1:8554/cam", format="rtsp")
encoder = H264Encoder(bitrate=10000000)
picam2.start_recording(encoder, output)
```

### HDR Mode

#### Camera Module 3 HDR
```python
from picamera2.devices.imx708 import IMX708

# Enable HDR mode before creating Picamera2
with IMX708(0) as cam:
    cam.set_sensor_hdr_mode(True)

picam2 = Picamera2(0)
# Now use normally
```

#### Pi 5 HDR
```python
import libcamera

# Enable Pi 5 HDR mode
picam2.set_controls({'HdrMode': libcamera.controls.HdrModeEnum.SingleExposure})

# Use delay for temporal denoise
picam2.switch_mode_and_capture_file(capture_config, "hdr.jpg", delay=10)
```

### AI Accelerator Integration

#### Hailo AI
```python
from picamera2.devices.hailo import Hailo

with Hailo("/path/to/model.hef") as hailo:
    model_h, model_w, _ = hailo.get_input_shape()

    config = picam2.create_preview_configuration(
        main={'size': (model_w, model_h), 'format': 'RGB888'}
    )
    picam2.configure(config)
    picam2.start()

    frame = picam2.capture_array()
    results = hailo.run(frame)
```

#### IMX500 AI
```python
from picamera2.devices import IMX500

imx500 = IMX500("/path/to/model.rpk")
picam2 = Picamera2()
picam2.start()

metadata = picam2.capture_metadata()
network_outputs = imx500.get_outputs(metadata)
```

---

## Parameter Reference

### Configuration Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `transform` | Transform | Image rotation/mirroring |
| `colour_space` | ColorSpace | Color space (Sycc, Smpte170m, Rec709) |
| `buffer_count` | int | Number of buffer sets |
| `display` | str | Stream to display ("main", "lores", None) |
| `encode` | str | Stream to encode ("main", "lores", None) |
| `queue` | bool | Queue frames for faster capture |
| `sensor` | dict | Sensor mode configuration |
| `controls` | dict | Runtime control values |

### Stream Configuration

| Parameter | Type | Description |
|-----------|------|-------------|
| `size` | tuple | (width, height) in pixels |
| `format` | str | Pixel format (see format table) |

### Image Formats

| Format | Bits/Pixel | Memory (12MP) | Description |
|--------|------------|---------------|-------------|
| XBGR8888 | 32 | 48MB | RGB with alpha, Qt compatible |
| RGB888 | 24 | 36MB | Standard RGB, OpenCV compatible |
| YUV420 | 12 | 18MB | Memory efficient YUV |

### Camera Controls

| Control | Type | Range | Description |
|---------|------|-------|-------------|
| ExposureTime | int | Sensor dependent | Exposure time (μs) |
| AnalogueGain | float | Sensor dependent | Analog gain |
| DigitalGain | float | Read-only | Digital gain applied |
| AwbEnable | bool | True/False | Auto white balance |
| AeEnable | bool | True/False | Auto exposure |
| Brightness | float | -1.0 to 1.0 | Image brightness |
| Contrast | float | 0.0 to 32.0 | Image contrast |
| Saturation | float | 0.0 to 32.0 | Color saturation |
| Sharpness | float | 0.0 to 16.0 | Image sharpness |
| ColourGains | tuple | (0.0-32.0, 0.0-32.0) | (red_gain, blue_gain) |
| ScalerCrop | Rectangle | Sensor bounds | Digital zoom region |

---

## Code Examples

### Complete Still Capture Application

```python
#!/usr/bin/env python3
from picamera2 import Picamera2
from libcamera import Transform
import time

def capture_photos():
    # Initialize camera
    picam2 = Picamera2()

    # Configure for preview and capture
    preview_config = picam2.create_preview_configuration(
        transform=Transform(hflip=True)
    )
    capture_config = picam2.create_still_configuration(
        main={"size": (4056, 3040)},
        transform=Transform(hflip=True)
    )

    # Start preview
    picam2.configure(preview_config)
    picam2.start(show_preview=True)

    try:
        # Let camera settle
        time.sleep(2)

        # Take photos
        for i in range(5):
            print(f"Capturing image {i+1}/5...")
            picam2.switch_mode_and_capture_file(
                capture_config, f"photo_{i+1:03d}.jpg"
            )
            time.sleep(1)

    finally:
        picam2.stop()

if __name__ == "__main__":
    capture_photos()
```

### Video Recording with Motion Detection

```python
#!/usr/bin/env python3
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import CircularOutput
import cv2
import numpy as np
import time

def motion_detection_recording():
    picam2 = Picamera2()

    # Configure dual streams
    config = picam2.create_video_configuration(
        main={"size": (1920, 1080)},
        lores={"size": (320, 240), "format": "YUV420"}
    )
    picam2.configure(config)

    # Set up circular buffer recording
    encoder = H264Encoder(bitrate=10000000)
    output = CircularOutput(buffersize=150)  # 5 seconds at 30fps

    picam2.start_recording(encoder, output)
    picam2.start()

    # Motion detection variables
    prev_frame = None
    recording = False
    motion_start_time = 0

    try:
        while True:
            # Get low-res frame for motion detection
            frame = picam2.capture_array("lores")
            gray = cv2.cvtColor(frame, cv2.COLOR_YUV420p2GRAY)

            if prev_frame is not None:
                # Calculate frame difference
                diff = cv2.absdiff(prev_frame, gray)
                diff = cv2.GaussianBlur(diff, (5, 5), 0)
                _, thresh = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)

                # Count changed pixels
                motion_pixels = cv2.countNonZero(thresh)
                motion_detected = motion_pixels > 500

                if motion_detected and not recording:
                    print("Motion detected! Starting recording...")
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    output.fileoutput = f"motion_{timestamp}.h264"
                    output.start()
                    recording = True
                    motion_start_time = time.time()

                elif recording and (time.time() - motion_start_time > 10):
                    print("Recording stopped.")
                    output.stop()
                    recording = False

            prev_frame = gray.copy()
            time.sleep(0.1)

    except KeyboardInterrupt:
        pass
    finally:
        if recording:
            output.stop()
        picam2.stop_recording()
        picam2.stop()

if __name__ == "__main__":
    motion_detection_recording()
```

### Web Streaming Server

```python
#!/usr/bin/env python3
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
import io
import socketserver
from threading import Condition
from http import server
import time

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                print(f'Removed streaming client {self.client_address}: {str(e)}')
        else:
            self.send_error(404)
            self.end_headers()

PAGE = """\
<html>
<head>
<title>Picamera2 MJPEG Streaming</title>
</head>
<body>
<center><h1>Picamera2 MJPEG Streaming</h1></center>
<center><img src="stream.mjpg" width="640" height="480"></center>
</body>
</html>
"""

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def main():
    global output

    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
    output = StreamingOutput()
    picam2.start_recording(JpegEncoder(), FileOutput(output))

    try:
        address = ('', 8000)
        server = StreamingServer(address, StreamingHandler)
        print("Server starting at http://localhost:8000/")
        server.serve_forever()
    finally:
        picam2.stop_recording()

if __name__ == '__main__':
    main()
```

### Multi-Camera Synchronized Capture

```python
#!/usr/bin/env python3
from picamera2 import Picamera2
from libcamera import controls
import time

def synchronized_capture():
    # Check available cameras
    cameras = Picamera2.global_camera_info()
    if len(cameras) < 2:
        print("Need at least 2 cameras for synchronization")
        return

    # Create camera objects
    picam2_server = Picamera2(0)
    picam2_client = Picamera2(1)

    # Configure both cameras with sync controls
    server_config = picam2_server.create_preview_configuration(
        controls={
            'FrameRate': 30.0,
            'SyncMode': controls.rpi.SyncModeEnum.Server,
            'SyncFrames': 10
        }
    )

    client_config = picam2_client.create_preview_configuration(
        controls={
            'FrameRate': 30.0,
            'SyncMode': controls.rpi.SyncModeEnum.Client
        }
    )

    # Start cameras
    picam2_server.configure(server_config)
    picam2_client.configure(client_config)

    picam2_server.start()
    picam2_client.start()

    try:
        # Wait for synchronization
        print("Waiting for cameras to synchronize...")

        server_req = picam2_server.capture_sync_request()
        client_req = picam2_client.capture_sync_request()

        print("Cameras synchronized!")
        print(f"Server sync error: {server_req.get_metadata().get('SyncTimer', 'N/A')} μs")
        print(f"Client sync error: {client_req.get_metadata().get('SyncTimer', 'N/A')} μs")

        # Capture synchronized images
        for i in range(5):
            print(f"Capturing synchronized pair {i+1}/5...")

            server_req = picam2_server.capture_request()
            client_req = picam2_client.capture_request()

            server_req.save("main", f"server_{i+1:03d}.jpg")
            client_req.save("main", f"client_{i+1:03d}.jpg")

            server_req.release()
            client_req.release()

            time.sleep(1)

    finally:
        picam2_server.stop()
        picam2_client.stop()

if __name__ == "__main__":
    synchronized_capture()
```

---

This comprehensive reference covers all major aspects of Picamera2, from basic usage to advanced features. The library provides powerful capabilities for camera control, image processing, and video recording on Raspberry Pi systems while maintaining good performance and flexibility.