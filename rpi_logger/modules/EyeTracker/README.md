# EyeTracker Module - Pupil Labs Neon Integration

This module integrates the **Pupil Labs Neon** eye tracking glasses with TheLogger system,
providing real-time gaze tracking, scene video recording, and synchronized data export.

---

## Table of Contents

1. [Hardware Specifications](#hardware-specifications)
2. [Pupil Labs Real-Time API](#pupil-labs-real-time-api)
   - [API Capabilities](#api-capabilities)
   - [Available Data Streams](#available-data-streams)
   - [Data Field Reference](#data-field-reference)
   - [Simple API (Synchronous)](#simple-api-synchronous)
   - [Async API](#async-api)
   - [Device Status & Models](#device-status--models)
3. [Our Module Implementation](#our-module-implementation)
   - [How Video Configuration Works](#how-video-configuration-works)
   - [Module Architecture](#module-architecture)
   - [Data Output](#data-output)
   - [Configuration Reference](#configuration-reference)
4. [External Resources](#external-resources)

---

## Hardware Specifications

The Neon device streams at **fixed specifications** that cannot be changed via API:

| Stream | Resolution | Frame Rate | Notes |
|--------|------------|------------|-------|
| Scene Camera | 1600x1200 px | 30 Hz | 103° x 77° FOV |
| Eye Cameras | 384x192 px (192x192 per eye) | 200 Hz | Infrared |
| Gaze Data | N/A | Up to 200 Hz | Varies by companion phone |

**Gaze rate by phone:**

| Phone | Typical Rate |
|-------|--------------|
| OnePlus 10, Motorola Edge 40 Pro, Samsung S25 | 200 Hz |
| OnePlus 8 (older devices) | ~120 Hz after warmup |

Post-processing in Pupil Cloud can recompute gaze at full 200 Hz if needed.

---

## Pupil Labs Real-Time API

> **Documentation Links:**
> - [API Home](https://pupil-labs.github.io/pl-realtime-api/dev/)
> - [Simple API Reference](https://pupil-labs.github.io/pl-realtime-api/dev/api/simple/)
> - [Async API Reference](https://pupil-labs.github.io/pl-realtime-api/dev/api/async/)
> - [All Modules & Classes](https://pupil-labs.github.io/pl-realtime-api/dev/modules/)
> - [Under the Hood (RTSP/Protocol)](https://pupil-labs.github.io/pl-realtime-api/dev/guides/under-the-hood/)

### API Capabilities

**Can DO:**
- Discover devices via mDNS (`neon.local:8080`)
- Query device status (`device.get_status()`)
- Receive RTSP streams (video, gaze, IMU, events, audio)
- Start/stop recordings on device
- Send timestamped events/markers
- Manage recording templates
- Get camera calibration data
- Estimate time offset for synchronization

**Cannot DO:**
- Set video resolution
- Set frame rate
- Configure camera parameters
- Adjust exposure/gain programmatically

### Available Data Streams

| Stream | Description | Rate |
|--------|-------------|------|
| Scene Video | World camera frames (BGR, 1600x1200) | 30 Hz |
| Eye Video | Infrared eye camera frames (384x192) | 200 Hz |
| Gaze | x/y position, worn status, timestamps | Up to 200 Hz |
| IMU | Accelerometer + gyroscope | Continuous |
| Eye Events | Blinks, fixations, saccades | Event-driven |
| Audio | Headset microphone | Continuous |

### Data Field Reference

#### Gaze Data (`GazeData`)
| Field | Type | Description |
|-------|------|-------------|
| `x`, `y` | float | Gaze position in scene camera coordinates |
| `timestamp_unix_seconds` | float | Unix timestamp |
| `worn` | bool | Glasses worn status |
| `datetime` | property | Python datetime |
| `timestamp_unix_ns` | property | Nanosecond timestamp |

#### Extended Gaze (`EyestateGazeData`)
All `GazeData` fields plus:
- Pupil diameter
- Eyeball center coordinates
- Optical axis vectors

#### Per-Eye Gaze (`DualMonocularGazeData`)
- Separate `x`, `y` gaze points for left and right eyes

#### Eye Events

Eye events are streamed with a numeric `event_type` field to distinguish event categories:

| Class | `event_type` | Description |
|-------|--------------|-------------|
| `FixationEventData` | `0` | **Saccade** (completed) - includes amplitude, velocity metrics |
| `FixationEventData` | `1` | **Fixation** (completed) - includes position, duration, velocity |
| `FixationOnsetEventData` | `2` | **Saccade onset** - marks start of saccade |
| `FixationOnsetEventData` | `3` | **Fixation onset** - marks start of fixation |
| `BlinkEventData` | `4` | **Blink** - includes start/end timestamps |

**FixationEventData fields** (for both fixations and saccades):
- Start/end timestamps (nanoseconds)
- Start/end gaze coordinates (x, y pixels)
- Mean gaze position
- Amplitude (pixels and degrees)
- Velocity metrics (mean and maximum)

**Note:** The "Compute fixations" setting must be enabled on the Companion Device to receive these events.

#### IMU Data (`IMUData`)
| Field | Type | Description |
|-------|------|-------------|
| `timestamp_unix_seconds` | float | Unix timestamp |
| `timestamp_unix_ns` | property | Nanosecond timestamp |
| `accel_data.x`, `.y`, `.z` | float | Accelerometer readings (m/s²) |
| `gyro_data.x`, `.y`, `.z` | float | Gyroscope readings (rad/s) |
| `quaternion.w`, `.x`, `.y`, `.z` | float | Orientation quaternion |
| `temperature` | float | Sensor temperature |

#### Video Frames (`VideoFrame` / `SimpleVideoFrame`)
| Field | Type | Description |
|-------|------|-------------|
| `bgr_buffer()` / `bgr_pixels` | numpy array | Shape (height, width, 3), dtype uint8 |
| `timestamp_unix_seconds` | float | Frame timestamp |

#### Audio Frames (`AudioFrame`)
| Field | Type | Description |
|-------|------|-------------|
| `timestamp_unix_seconds` | float | Unix timestamp |
| `timestamp_unix_ns` | property | Nanosecond timestamp |
| `av_frame` | PyAV AudioFrame | Raw audio frame |
| `av_frame.sample_rate` | int | Sample rate (Hz) |
| `av_frame.layout.nb_channels` | int | Number of audio channels |
| `to_resampled_ndarray()` | method | Returns audio samples as numpy arrays |

#### Matched/Synchronized Data
```python
# Scene + Gaze (synchronized)
matched = device.receive_matched_scene_video_frame_and_gaze()
# matched.frame, matched.gaze

# Scene + Eyes + Gaze (synchronized)
matched = device.receive_matched_scene_and_eyes_video_frames_and_gaze()
# matched.scene, matched.eyes, matched.gaze

# Scene + Audio (synchronized)
matched = device.receive_matched_scene_video_frame_and_audio()
# matched.frame, matched.audio
```

#### Time Synchronization
```python
# Estimate clock offset between device and host
offsets = device.estimate_time_offset(number_of_measurements=100)
```

### Simple API (Synchronous)

The Simple API provides blocking/synchronous access to the device.

#### Setup & Discovery
```python
from pupil_labs.realtime_api.simple import Device, discover_one_device, discover_devices

# Direct connection
device = Device(address="192.168.1.100", port=8080)

# Auto-discovery
device = discover_one_device(max_search_duration_seconds=10.0)
devices = discover_devices(search_duration_seconds=5.0)  # Returns list[Device]
```

#### Device Properties
```python
device.address                  # IP address (str)
device.port                     # Port number (int)
device.dns_name                 # "neon.local" (str | None)
device.battery_level_percent    # Phone battery % (int)
device.battery_state            # "OK" | "LOW" | "CRITICAL"
device.memory_num_free_bytes    # Available phone memory (int)
device.memory_state             # "OK" | "LOW" | "CRITICAL"
device.phone_id, phone_name     # Device identifiers (str)
device.version_glasses          # 1=Pupil Invisible, 2=Neon, None
device.serial_number_glasses    # Hardware serial (str)
device.is_currently_streaming   # Streaming status (bool)
```

#### Receiving Data
```python
# Individual streams
gaze = device.receive_gaze_datum(timeout_seconds=1.0)
frame = device.receive_scene_video_frame(timeout_seconds=1.0)
eyes = device.receive_eyes_video_frame(timeout_seconds=1.0)
imu = device.receive_imu_datum(timeout_seconds=1.0)
event = device.receive_eye_events(timeout_seconds=1.0)
audio = device.receive_audio_frame(timeout_seconds=1.0)

# Synchronized data
matched = device.receive_matched_scene_video_frame_and_gaze(timeout_seconds=1.0)
```

#### Device Control
```python
device.streaming_start("gaze")          # Start specific stream
device.streaming_stop()                 # Stop all streams
recording_id = device.recording_start() # Returns recording ID
device.recording_stop_and_save()
device.recording_cancel()
device.send_event("marker_name", timestamp_unix_ns=...)
device.close()                          # Always call when done
```

### Async API

The Async API provides non-blocking access using `async/await`.

#### Setup & Discovery
```python
from pupil_labs.realtime_api import Device, Network, discover_devices

# Auto-discovery
async for device_info in discover_devices(timeout_seconds=5.0):
    device = Device(device_info.address, device_info.port)

# Using Network class
network = Network()
device_info = await network.wait_for_new_device(timeout_seconds=10.0)
await network.close()
```

#### Device Methods
```python
# Recording control
recording_id = await device.recording_start()  # Returns recording ID (str)
await device.recording_stop_and_save()
await device.recording_cancel()

# Events & markers
event = await device.send_event("marker", event_timestamp_unix_ns=...)

# Templates
template = await device.get_template()
data = await device.get_template_data(template_format="simple")  # "simple" | "api"
await device.post_template_data(data, template_format="simple")

# Status & calibration
status = await device.get_status()
calibration = await device.get_calibration()

# Status streaming (async generator)
async for component in device.status_updates():
    ...

await device.close()
```

#### RTSP Streaming
```python
from pupil_labs.realtime_api.streaming import receive_video_frames, receive_gaze_data

async for frame in receive_video_frames(rtsp_url):
    bgr_array = frame.bgr_buffer()  # numpy array (height, width, 3)
    timestamp = frame.timestamp_unix_seconds

async for gaze in receive_gaze_data(rtsp_url):
    x, y = gaze.x, gaze.y
    worn = gaze.worn
```

### Device Status & Models

#### Status Model
```python
status = await device.get_status()
status.phone      # Phone/companion device info
status.hardware   # Glasses connection details
status.sensors    # List of Sensor objects with RTSP URLs
status.recording  # Current recording state or None
```

#### Sensor Model
```python
sensor.sensor      # Sensor type (e.g., SensorName.WORLD)
sensor.conn_type   # Connection type
sensor.connected   # Boolean
sensor.url         # Computed RTSP URL: "rtsp://{ip}:{port}/?{params}"
sensor.params      # Opaque parameter string
```

#### RTSP URLs
```
rtsp://<device_ip>:8086/?camera=world   # Scene camera (1600x1200 @ 30Hz)
rtsp://<device_ip>:8086/?camera=gaze    # Gaze data stream
rtsp://<device_ip>:8086/?camera=eyes    # Eye cameras (384x192 @ 200Hz)
rtsp://<device_ip>:8086/live/imu        # IMU data
rtsp://<device_ip>:8086/live/events     # Eye events (blinks, fixations, saccades)
rtsp://<device_ip>:8086/?audio=scene    # Headset microphone
```

#### Available Classes

| Category | Classes |
|----------|---------|
| **Device Management** | `Device`, `Network`, `DeviceError` |
| **Data Models** | `Status`, `Event`, `Template`, `Calibration` |
| **Gaze Data** | `GazeData`, `DualMonocularGazeData`, `EyestateGazeData` |
| **Eye Events** | `BlinkEventData`, `FixationEventData`, `FixationOnsetEventData` |
| **Media** | `VideoFrame`, `AudioFrame` |
| **RTSP Streamers** | `RTSPVideoFrameStreamer`, `RTSPGazeStreamer`, `RTSPAudioStreamer`, `RTSPEyeEventStreamer`, `RTSPImuStreamer`, `RTSPRawStreamer` |
| **Utilities** | `APIPath`, `StatusUpdateNotifier`, `RTSPData` |

---

## Our Module Implementation

### How Video Configuration Works

The Neon API is **receive-only** - we cannot request specific resolutions or frame rates.
Our module receives whatever the device streams, then processes locally:

```
Neon Device (streams 1600x1200 @ 30Hz via RTSP)
        │
        ▼
device.get_status() → retrieves sensor URLs (not configuration)
        │
        ▼
StreamHandler receives raw frames asynchronously
        │
        ▼
VideoEncoder resizes to configured resolution (e.g., 1280x720)
        │
        ▼
VideoEncoder writes at configured FPS (e.g., 10 fps)
        │
        ▼
Output MP4 file on disk
```

**Benefits of local processing:**
- Reduced file sizes (downscale from 1600x1200)
- Lower storage requirements (subsample from 30 fps)
- Matching frame rates with other synchronized cameras

### Module Architecture

```
EyeTracker/
├── config.txt                 # Module configuration
├── main_eye_tracker.py        # Entry point
├── app/
│   ├── main_eye_tracker.py    # Application launcher
│   ├── eye_tracker_runtime.py # Runtime management
│   └── view.py                # GUI implementation
└── tracker_core/
    ├── gaze_tracker.py        # Main tracking orchestrator
    ├── device_manager.py      # Neon device discovery & status
    ├── stream_handler.py      # RTSP stream reception
    ├── frame_processor.py     # Frame scaling & overlay rendering
    ├── rolling_fps.py         # FPS calculation (5-second window)
    ├── config/
    │   ├── tracker_config.py  # TrackerConfig dataclass
    │   └── config_loader.py   # config.txt parser
    ├── recording/
    │   ├── manager.py         # Recording session management
    │   ├── video_encoder.py   # FFmpeg/OpenCV video writer
    │   └── async_csv_writer.py# Async CSV data export
    └── interfaces/
        └── gui/               # Configuration dialogs
```

### Data Output

#### Video Files
Named: `{prefix}_GAZE_{width}x{height}_{fps}fps.mp4`

Example: `session_GAZE_1280x720_10fps.mp4`

#### CSV Data Files
| File | Contents |
|------|----------|
| `gaze.csv` | Gaze coordinates, timestamps, worn state |
| `frame_timing.csv` | Frame sync metadata |
| `imu.csv` | Accelerometer/gyroscope data |
| `eye_events.csv` | Blinks, fixations, saccades |
| `device_status.csv` | Battery, storage telemetry (optional) |

#### Frame Timing Metadata
The `frame_timing.csv` records synchronization data:
```csv
frame_number, capture_monotonic, capture_unix, camera_frame_index,
available_camera_fps, requested_fps, dropped_frames_total
```

### Configuration Reference

#### Core Capture
```ini
target_fps = 10.0              # Output file frame rate (1-120, recommended 5-30)
resolution_width = 1280        # Output video width
resolution_height = 720        # Output video height
```

#### Preview & GUI
```ini
preview_preset = 4             # 0=1600x1200 ... 4=640x480 ... 8=160x120
gui_preview_update_hz = 5      # GUI refresh rate
```

#### Recording Overlay
```ini
enable_recording_overlay = true
include_gaze_in_recording = true
gaze_shape = circle            # circle | cross
gaze_circle_radius = 10
```

#### Data Export
```ini
enable_advanced_gaze_logging = false   # Per-eye metrics
expand_eye_event_details = true        # Detailed event fields
enable_audio_recording = false         # Headset microphone
enable_device_status_logging = false   # Battery/storage log
```

#### Device Discovery
```ini
discovery_timeout = 5.0        # Seconds to wait for headset
discovery_retry = 3.0          # Seconds between retries
```

#### Frame Selection Modes
| Mode | Behavior |
|------|----------|
| `timer` | Maintain consistent output FPS by repeating frames if needed |
| `camera` | Only write unique camera frames (variable output rate) |

---

## External Resources

### Pupil Labs Real-Time API
- [API Documentation Home](https://pupil-labs.github.io/pl-realtime-api/dev/)
- [Simple API Reference](https://pupil-labs.github.io/pl-realtime-api/dev/api/simple/)
- [Async API Reference](https://pupil-labs.github.io/pl-realtime-api/dev/api/async/)
- [All Modules & Classes](https://pupil-labs.github.io/pl-realtime-api/dev/modules/)
- [Under the Hood (RTSP/Protocol)](https://pupil-labs.github.io/pl-realtime-api/dev/guides/under-the-hood/)
- [GitHub Repository](https://github.com/pupil-labs/pl-realtime-api)

### Neon Hardware Documentation
- [Neon Data Streams (Hardware Specs)](https://docs.pupil-labs.com/neon/data-collection/data-streams/)
- [Neon Documentation Home](https://docs.pupil-labs.com/neon/)
- [Neon Real-Time API Overview](https://docs.pupil-labs.com/neon/real-time-api/)

### Pupil Labs GitHub
- [Pupil Labs Organization](https://github.com/pupil-labs)
