# Cameras Module

The Cameras module captures synchronized video from Raspberry Pi camera modules (IMX296, etc.) and USB webcams. Each camera runs in its own module instance with configurable resolution and frame rate, allowing you to capture multiple camera views simultaneously.

Cameras are discovered by the main logger and appear in the Devices panel. Click Connect to launch a camera window.

---

## Getting Started

1. Connect your camera (CSI ribbon cable or USB)
2. Enable "Cameras" in the Modules menu
3. The camera appears in the Devices panel when detected
4. Click Connect to launch this camera's window
5. Adjust settings if needed via the Controls menu
6. Start a session to begin recording

---

## User Interface

### Preview Display

Shows a live feed from this camera instance:
- Preview runs at reduced resolution for performance
- Each camera has its own dedicated window

### Settings Window

Access via **Controls > Show Settings Window**:

| Setting | Description |
|---------|-------------|
| Preview Resolution | Display size (320x240 to 640x480) |
| Preview FPS | Live view frame rate (1-15) |
| Record Resolution | Capture size (up to sensor maximum) |
| Record FPS | Recording frame rate (1-60+) |

### IO Metrics Bar

Shows real-time performance data:

| Metric | Description |
|--------|-------------|
| Cam | Active camera ID |
| In | Input frame rate (from sensor) |
| Rec | Recording output rate |
| Tgt | Target recording FPS |
| Prv | Preview output rate |
| Q | Queue depths (preview/record) |
| Wait | Frame wait time (ms) |

---

## Recording Sessions

### Starting Recording

When you start a recording session:
- Video capture begins to an AVI file
- Frame timing is logged to a companion CSV
- Recording metadata is saved to a separate CSV

### During Recording

- Timestamp overlay shows real-time clock and frame number
- Queue metrics help you monitor if recording is keeping up
- One video file per camera per trial

---

## Data Output

### File Location

```
{session_dir}/Cameras/{camera_id}/
```

### Files Generated

| File | Description |
|------|-------------|
| `{prefix}_{camera_id}.avi` | Video file |
| `{prefix}_{camera_id}_timing.csv` | Per-frame timing data |
| `{prefix}_{camera_id}_metadata.csv` | Recording session info |

Example: `trial_001_usb_0_001.avi`

### Video File Format

| Property | Value |
|----------|-------|
| Container | AVI |
| Codec | MJPEG (Motion JPEG) |
| Pixel Format | YUV420P |
| Resolution | Configurable (default 1280x720) |
| Frame Rate | Configurable (default 30 fps) |

The timestamp overlay shows: `YYYY-MM-DDTHH:MM:SS.mmm #frame`

### Timing CSV Columns (9 fields)

The timing CSV contains per-frame timing for precise synchronization with other modules.

| Column | Description |
|--------|-------------|
| trial | Trial number (integer, 1-based) |
| module | Module name ("Cameras") |
| device_id | Camera device identifier |
| label | Optional label (blank if unused) |
| record_time_unix | Wall clock time when captured (Unix seconds, 6 decimals) |
| record_time_mono | Monotonic time when encoded (seconds, 9 decimals) |
| frame_index | 1-based frame number in video file |
| sensor_timestamp_ns | Hardware sensor timestamp in nanoseconds (CSI cameras only) |
| video_pts | Presentation timestamp in video stream |

**Example row:**
```
1,Cameras,usb_0_001,,1733649120.123456,123.456789012,1,1733649120123456789,1
```

**Note:** `sensor_timestamp_ns` is only available for CSI cameras (Picamera2). USB cameras show empty/None for this field.

### Metadata CSV Columns

Session-level information about the recording:

| Column | Description |
|--------|-------------|
| camera_id | Camera identifier (e.g., "usb_0_001") |
| backend | Camera type ("usb" or "picam") |
| start_time_unix | Session start (Unix seconds) |
| end_time_unix | Session end (Unix seconds) |
| target_fps | FPS used for encoding |
| resolution_width | Video frame width (pixels) |
| resolution_height | Video frame height (pixels) |
| video_path | Path to video file |
| timing_path | Path to timing CSV |

### Timing and Synchronization

**Timestamp Precision:**
- capture_time_unix: Microsecond precision (6 decimals)
- encode_time_mono: Nanosecond precision (9 decimals)
- sensor_timestamp_ns: Nanosecond precision (CSI cameras only)

**Frame Timing Notes:**
- USB cameras: Actual FPS may differ from requested. The encoder uses actual camera FPS to ensure video playback matches real-world timing.
- CSI cameras (Picamera2): Hardware-enforced FPS for consistent timing.

**Cross-Module Synchronization:**
- Use `encode_time_mono` or `capture_time_unix` for cross-module sync
- Frame index in CSV matches video frame position exactly
- CSV row count equals number of frames in video file

**Finding a Video Frame at Time T:**
1. Search timing CSV for nearest `capture_time_unix`
2. Use `frame_index` to seek in video file

---

## Camera Types

### Raspberry Pi Camera Modules (CSI)

| Model | Feature | Use Case |
|-------|---------|----------|
| IMX296 | Global shutter | No motion blur - ideal for fast-moving subjects and precise timing studies |
| IMX219/IMX477 | Rolling shutter | General purpose photography |

CSI cameras provide hardware sensor timestamps (`sensor_timestamp_ns`) for maximum timing accuracy.

### USB Cameras

- UVC-compatible webcams
- No hardware timestamps (use `encode_time_mono` instead)
- Actual FPS may vary from requested depending on USB bandwidth and camera capability

---

## Configuration

### Default Settings

| Setting | Default | Notes |
|---------|---------|-------|
| Capture Resolution | 1280x720 | Use native sensor resolution for best quality |
| Capture FPS | 30.0 | Match your experiment requirements |
| Preview Size | 320x180 | Lower = smoother preview |
| Preview FPS | 10.0 | 5-10 is usually sufficient for monitoring |
| JPEG Quality | 80 | Balance between quality and file size |

### Preview Settings

For the live display - keep these low for smooth performance:
- Resolution: 320x240 recommended
- FPS: 5-10 is usually sufficient for monitoring

### Record Settings

For saved video:
- Resolution: Use native sensor resolution for best quality
- FPS: Match your experiment requirements (30 or 60 typical)

---

## Troubleshooting

### Camera not appearing in Devices panel

1. Check physical connection (ribbon cable for CSI, USB for webcams)
2. Verify USB cameras are recognized by your operating system
3. Enable "Cameras" in the Modules menu
4. On Raspberry Pi: Run `libcamera-hello` or check `raspi-config` camera settings
5. On Linux: Run `v4l2-ctl --list-devices`
6. On macOS/Windows: Check system camera permissions for the application

### Preview is laggy

1. Lower preview resolution (320x240)
2. Reduce preview FPS (5 fps)
3. Check CPU usage on the system
4. Close other applications

### Recording drops frames

1. Lower record FPS or resolution
2. Use a faster SD card or SSD
3. Check available disk space
4. Monitor the Q (queue) metrics - high values indicate backpressure

### Black or corrupted video

1. Check camera ribbon cable for damage (CSI cameras)
2. Verify camera module is seated properly
3. Test camera with your OS camera app or another application
4. Check application has permission to access camera

### Empty sensor_timestamp_ns in CSV

This is normal for USB cameras - they don't provide hardware timestamps. Use `encode_time_mono` for synchronization instead.
