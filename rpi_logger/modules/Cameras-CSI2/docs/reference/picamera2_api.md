# Picamera2 API Reference

> Key APIs and gotchas for CSI camera capture

## Getting Sensor Timestamp

### Wrong Way (loses metadata)

```python
frame = camera.capture_array("main")
# No way to get SensorTimestamp!
```

### Correct Way

```python
request = camera.capture_request()
metadata = request.get_metadata()
sensor_timestamp_ns = metadata.get("SensorTimestamp")
array = request.make_array("main")
request.release()  # Important - releases the buffer back to pool
```

**Why this matters**: `capture_array()` is a convenience method that discards metadata. For scientific capture, we need the hardware timestamp.

---

## Strict Frame Rate Control

```python
# For exact 30 FPS with no tolerance
frame_duration_us = int(1_000_000 / 30)  # 33333 μs
config = camera.create_video_configuration(
    controls={"FrameDurationLimits": (frame_duration_us, frame_duration_us)}
)
```

Setting `min=max` tells the sensor to maintain strict timing. However, the sensor may not achieve exactly the requested rate - use software gating for precise FPS.

---

## Available Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `SensorTimestamp` | int | Nanoseconds since camera boot |
| `FrameDuration` | int | Actual frame duration in μs |
| `ExposureTime` | int | Exposure time in μs |
| `AnalogueGain` | float | Analog gain applied |
| `DigitalGain` | float | Digital gain applied |
| `Lux` | float | Estimated scene illumination |
| `ColourTemperature` | int | Estimated color temperature |

---

## Request Lifecycle

```python
# 1. Capture a request (blocks until frame ready)
request = camera.capture_request()

# 2. Extract everything you need
metadata = request.get_metadata()
array = request.make_array("main")

# 3. Release ASAP to return buffer to pool
request.release()

# 4. Now process the array (after release)
process_frame(array, metadata)
```

**Critical**: Call `release()` as soon as possible. The camera has a limited buffer pool, and holding requests can cause frame drops.

---

## Configuration for Scientific Capture

```python
config = camera.create_video_configuration(
    main={"format": "YUV420", "size": (1456, 1088)},
    controls={
        "FrameDurationLimits": (16667, 16667),  # 60 FPS
        "AeEnable": False,  # Manual exposure for consistency
    },
    buffer_count=4,  # Enough for pipeline without excess memory
)
camera.configure(config)
```

---

## Common Gotchas

### 1. Buffer Count

Too low (2): Frame drops when processing is slow
Too high (8+): Increased latency and memory usage

**Recommended**: 4 buffers for balanced performance

### 2. Format Selection

| Format | Size | Processing |
|--------|------|------------|
| YUV420 | Smallest | Need to convert to RGB for display |
| RGB888 | 3x YUV420 | Ready for display, larger buffers |
| BGR888 | 3x YUV420 | OpenCV native format |

**Recommended**: YUV420 for capture, convert to RGB only for preview

### 3. Controls Timing

Controls set via `camera.set_controls()` take effect on the NEXT frame, not immediately. For time-critical changes, account for this delay.

### 4. Thread Safety

Picamera2 is NOT thread-safe. Access camera object only from one thread. Use queues for cross-thread communication.

---

## Encoder Usage

### MJPEG Encoder

```python
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FfmpegOutput

encoder = JpegEncoder(q=85)  # Quality 85
output = FfmpegOutput(str(video_path))

camera.start_recording(encoder, output)
# ... record frames ...
camera.stop_recording()
```

**Note**: This uses the hardware JPEG encoder, which is efficient on Pi 5.

### Manual Frame Encoding

For more control, encode frames manually:

```python
import cv2

# In capture loop
request = camera.capture_request()
array = request.make_array("main")
request.release()

# Convert and encode
rgb = cv2.cvtColor(array, cv2.COLOR_YUV420p2RGB)
_, jpeg = cv2.imencode('.jpg', rgb, [cv2.IMWRITE_JPEG_QUALITY, 85])
```

---

## Debugging

### Check camera capabilities

```python
from picamera2 import Picamera2

camera = Picamera2()
print(camera.camera_properties)
print(camera.sensor_modes)
```

### Monitor frame timing

```python
request = camera.capture_request()
metadata = request.get_metadata()
print(f"Frame duration: {metadata.get('FrameDuration')} μs")
print(f"Exposure time: {metadata.get('ExposureTime')} μs")
request.release()
```
