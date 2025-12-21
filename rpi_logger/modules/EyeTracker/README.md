# EyeTracker Module - Pupil Labs Neon

The EyeTracker-Neon module captures gaze data and scene video from Pupil Labs Neon eye tracking glasses. It records where participants are looking in real-time, synchronized with other data streams for multi-modal research.

The Neon tracker connects via network (WiFi or USB tethering).

---

## Getting Started

1. Power on your Pupil Labs Neon glasses
2. Connect via WiFi (same network as host) or USB tethering
3. Enable the EyeTracker-Neon module from the Modules menu
4. Wait for device connection (status shows "Connected")
5. Calibrate if needed using the Neon Companion app
6. Start a session to begin recording

---

## User Interface

### Preview Display

Shows the scene camera feed with gaze overlay:
- Red circle indicates current gaze position
- Scene video shows participant's view

### Device Status Panel

| Field | Description |
|-------|-------------|
| Device | Connected device name |
| Status | Connection state (Connected/Disconnected) |
| Recording | Current recording state (Active/Idle) |

### Controls

- **Configure** - Open device settings dialog

---

## Recording Sessions

### Starting Recording

When you start a recording session:
- Gaze data recording begins
- Scene video capture starts
- Optional: Eye camera video, IMU, audio, and events

### During Recording

Each sample captures:
- Gaze coordinates (x, y) in scene camera view
- Pupil diameter for each eye
- Confidence values for gaze estimation
- Scene video with embedded timestamps

---

## Hardware Specifications

The Neon device streams at **fixed specifications** that cannot be changed via API:

| Stream | Resolution | Frame Rate | Notes |
|--------|------------|------------|-------|
| Scene Camera | 1600x1200 px | 30 Hz | 103° x 77° field of view |
| Eye Cameras | 384x192 px (192x192 per eye) | 200 Hz | Infrared |
| Gaze Data | N/A | Up to 200 Hz | Varies by companion phone |

Our module receives these streams and can downsample/resize locally for smaller file sizes.

---

## Data Output

### File Location

```
{session_dir}/EyeTracker-Neon/
```

### Files Generated

| File | Description |
|------|-------------|
| `{prefix}_GAZEDATA_trial{NNN}.csv` | Extended gaze data with pupil diameter |
| `{prefix}_SCENE_trial{NNN}.mp4` | Scene video (participant's view) |
| `{prefix}_EVENT_trial{NNN}.csv` | Eye events (fixations, saccades, blinks) |
| `{prefix}_IMU_trial{NNN}.csv` | Head motion (accelerometer, gyroscope) |
| `{prefix}_FRAME_trial{NNN}.csv` | Video frame timing |
| `{prefix}_AUDIO_trial{NNN}.wav` | Scene microphone audio (optional) |

### Scene Video Format

| Property | Value |
|----------|-------|
| Container | MP4 |
| Codec | H.264 |
| Resolution | Configurable (default 1280x720, downsampled from 1600x1200) |
| Frame Rate | Configurable (default 10 fps, downsampled from 30 Hz) |

### GAZE CSV Columns (36 fields)

Gaze data with standard prefix columns followed by device-specific measurements:

| Column | Description |
|--------|-------------|
| trial | Trial number (integer, 1-based) |
| module | Module name ("EyeTracker") |
| device_id | Device identifier ("eye_tracker") |
| label | Optional trial label |
| record_time_unix | System capture time (Unix seconds, 6 decimals) |
| record_time_mono | Monotonic capture time (seconds, 9 decimals) |
| timestamp | Device gaze timestamp (Unix seconds) |
| timestamp_ns | Device timestamp in nanoseconds |
| stream_type | Data stream type |
| worn | Glasses worn status (0/1) |
| x, y | Normalized gaze position (0-1) |
| left_x, left_y | Left eye gaze (0-1) |
| right_x, right_y | Right eye gaze (0-1) |
| pupil_diameter_left | Left pupil diameter (mm) |
| pupil_diameter_right | Right pupil diameter (mm) |
| eyeball_center_*_x/y/z | 3D eye center positions |
| optical_axis_*_x/y/z | 3D gaze direction vectors |
| eyelid_*_top/bottom | Eyelid angles |
| eyelid_aperture_* | Eyelid openness |

### EVENTS CSV Columns (24 fields)

Eye events with standard prefix columns:

| Column | Description |
|--------|-------------|
| trial | Trial number (integer, 1-based) |
| module | Module name ("EyeTracker") |
| device_id | Device identifier ("eye_tracker") |
| label | Optional trial label |
| record_time_unix | System capture time (Unix seconds, 6 decimals) |
| record_time_mono | Monotonic capture time (seconds, 9 decimals) |
| timestamp | Device event timestamp (Unix seconds) |
| timestamp_ns | Device timestamp in nanoseconds |
| event_type | fixation, blink, or saccade |
| event_subtype | Event category |
| confidence | Event confidence (0-1) |
| duration | Event duration (seconds) |
| start_time_ns, end_time_ns | Event time range |
| start_gaze_x/y, end_gaze_x/y | Gaze positions |
| mean_gaze_x/y | Average gaze position |
| amplitude_pixels, amplitude_angle_deg | Saccade amplitude |
| mean_velocity, max_velocity | Saccade velocity |

### IMU CSV Columns (19 fields)

Head motion data with standard prefix columns:

| Column | Description |
|--------|-------------|
| trial | Trial number (integer, 1-based) |
| module | Module name ("EyeTracker") |
| device_id | Device identifier ("eye_tracker") |
| label | Optional trial label |
| record_time_unix | System capture time (Unix seconds, 6 decimals) |
| record_time_mono | Monotonic capture time (seconds, 9 decimals) |
| timestamp | Device IMU timestamp (Unix seconds) |
| timestamp_ns | Device timestamp in nanoseconds |
| gyro_x, gyro_y, gyro_z | Gyroscope (rad/s) |
| accel_x, accel_y, accel_z | Accelerometer (m/s²) |
| quat_w, quat_x, quat_y, quat_z | Orientation quaternion |
| temperature | Sensor temperature |

### FRAME CSV Columns (6 fields)

Video frame timing for synchronization:

| Column | Description |
|--------|-------------|
| Module | Always "EyeTracker-Neon" |
| trial | Trial number |
| frame_index | 1-based frame number in video |
| capture_timestamp | Device capture time (Unix seconds) |
| record_time_unix | System time when recorded |
| record_time_mono | Monotonic time (seconds, 9 decimals) |

### Timing and Synchronization

**Timestamp Types:**

| Timestamp | Source | Use Case |
|-----------|--------|----------|
| gaze_timestamp | Pupil Labs device clock | Primary gaze timing |
| record_time_unix | Host system wall clock | Cross-system time reference |
| record_time_mono | Host monotonic clock | Cross-module synchronization (best for this) |

**Cross-Module Synchronization:**
Use `record_time_mono` for precise cross-module sync with:
- Camera `encode_time_mono`
- Audio `record_time_mono`
- DRT `record_time_mono`/`record_time_unix`

**Video-Gaze Alignment:**
Use FRAME CSV to correlate video frames with gaze data:
1. Find `frame_index` for desired video position
2. Match `capture_timestamp` to `gaze_timestamp` in GAZEDATA
3. Gaze samples between frames belong to that time period

---

## Data Interpretation

### Gaze Position (norm_pos_x, norm_pos_y)

Normalized coordinates (0-1) in scene camera view:
- (0, 0) = top-left corner
- (1, 1) = bottom-right corner

To convert to pixel coordinates:
```
pixel_x = norm_pos_x * scene_width
pixel_y = norm_pos_y * scene_height
```

### Confidence

Quality of gaze estimate (0-1). Higher values indicate more reliable tracking. Low confidence may occur when:
- Eyes are partially closed
- Glasses are slipping
- Infrared reflections interfere

### Pupil Diameter

Measured in millimeters. Changes in pupil size can reflect:
- Cognitive load (larger during mental effort)
- Emotional response
- Lighting conditions (smaller in bright light)

---

## Calibration

For accurate gaze data, calibrate before each session:

1. Open the Neon Companion app on the connected phone
2. Select appropriate calibration method
3. Follow on-screen instructions
4. Verify accuracy with validation targets

**Recalibrate if:**
- Glasses are repositioned on the participant's face
- Significant time has passed
- Gaze accuracy appears poor

---

## Configuration

Click **"Configure"** to access device settings.

| Setting | Default | Description |
|---------|---------|-------------|
| Scene Resolution | 1280x720 | Output video resolution (downsampled from 1600x1200) |
| Scene FPS | 10 | Output frame rate (downsampled from 30 Hz) |
| Eyes FPS | 30 | Eye camera output rate (downsampled from 200 Hz) |
| Preview Preset | 4 (640x480) | Live preview resolution (0-8 scale) |
| Gaze Overlay | Enabled | Draw gaze position on recorded video |
| Audio Recording | Disabled | Record scene microphone audio |

---

## Troubleshooting

### Device not detected

1. Check USB cable connection or WiFi network
2. Verify Neon Companion app is running on the phone
3. Check network settings if using WiFi (both devices on same network)
4. Restart the module if needed

### No gaze data appearing

1. Ensure calibration was completed
2. Check pupil detection in Neon Companion app
3. Verify adequate lighting conditions
4. Clean eye camera lenses (infrared cameras on inside of frame)

### Scene video not recording

1. Check scene camera connection
2. Verify camera is not in use by another app
3. Check available disk space
4. Review module logs for errors

### Poor gaze accuracy

1. Recalibrate the tracker
2. Ensure glasses fit snugly (not slipping)
3. Check for reflections on lenses
4. Verify pupil detection is stable in Companion app

---

## External Resources

- [Pupil Labs Neon Documentation](https://docs.pupil-labs.com/neon/)
- [Neon Real-Time API](https://docs.pupil-labs.com/neon/real-time-api/)
- [Python Real-Time API Reference](https://pupil-labs.github.io/pl-realtime-api/dev/)
