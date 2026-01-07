# Output Format Specifications

## Video File

### Format Details

| Property | Value |
|----------|-------|
| Container | AVI |
| Codec | Motion JPEG (MJPEG) |
| Pixel Format | YUV420P |
| Default Resolution | 1280x720 |
| Default FPS | 30 |
| Quality | 80 (configurable) |

### Filename Pattern

```
{session_prefix}_{camera_label}.avi
```

Example: `session_001_logitech_c920.avi`

### Timestamp Overlay (Optional)

When enabled, burns timestamp into video:

```
2024-01-15T14:32:05.123 #00001
```

Format: `{ISO timestamp with ms} #{frame number, 5 digits}`

Position: Top-left corner, white text with black outline

---

## Timing CSV

Per-frame timing data for synchronization.

### Filename Pattern

```
{session_prefix}_{camera_label}_timing.csv
```

### Schema

| Column | Type | Description |
|--------|------|-------------|
| trial | int | Trial number |
| module | str | Always "Cameras-USB2" |
| device_id | str | Camera stable ID |
| label | str | Camera label (may be empty) |
| record_time_unix | float | Wall clock (6 decimal places) |
| record_time_mono | float | Monotonic time (9 decimal places) |
| frame_index | int | 1-based frame number |
| sensor_timestamp_ns | int | Hardware timestamp (0 for USB) |
| video_pts | int | Presentation timestamp in video |

### Example

```csv
trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,sensor_timestamp_ns,video_pts
1,Cameras-USB2,usb-0000:00:14.0-2,logitech_c920,1705329125.123456,12345.678901234,1,0,0
1,Cameras-USB2,usb-0000:00:14.0-2,logitech_c920,1705329125.156789,12345.712234567,2,0,33333
1,Cameras-USB2,usb-0000:00:14.0-2,logitech_c920,1705329125.190123,12345.745567890,3,0,66666
```

### Notes

- `record_time_mono` uses `time.monotonic()` for drift-free timing
- `video_pts` is in timebase units (typically microseconds)
- `sensor_timestamp_ns` is always 0 for USB cameras (no hardware timestamp)

---

## Metadata CSV

Session-level metadata.

### Filename Pattern

```
{session_prefix}_{camera_label}_metadata.csv
```

### Schema

| Column | Type | Description |
|--------|------|-------------|
| camera_id | str | Full camera ID |
| backend | str | "usb" |
| name | str | Camera name |
| device_path | str | /dev/videoX |
| start_time_unix | float | Recording start |
| end_time_unix | float | Recording end |
| target_fps | float | Requested FPS |
| actual_fps | float | Achieved FPS |
| resolution_width | int | Width in pixels |
| resolution_height | int | Height in pixels |
| pixel_format | str | "MJPG" |
| video_path | str | Path to video file |
| timing_path | str | Path to timing CSV |
| frames_total | int | Total frames recorded |

### Example

```csv
camera_id,backend,name,device_path,start_time_unix,end_time_unix,target_fps,actual_fps,resolution_width,resolution_height,pixel_format,video_path,timing_path,frames_total
usb:usb-0000:00:14.0-2,usb,Logitech C920,/dev/video0,1705329125.123,1705329186.456,30.0,29.97,1280,720,MJPG,/data/session_001_logitech_c920.avi,/data/session_001_logitech_c920_timing.csv,1847
```

---

## Directory Structure

```
{output_dir}/
├── {session_prefix}_{camera1}.avi
├── {session_prefix}_{camera1}_timing.csv
├── {session_prefix}_{camera1}_metadata.csv
├── {session_prefix}_{camera2}.avi
├── {session_prefix}_{camera2}_timing.csv
└── {session_prefix}_{camera2}_metadata.csv
```

With per-camera subdirs enabled:

```
{output_dir}/
├── camera1/
│   ├── {session_prefix}.avi
│   ├── {session_prefix}_timing.csv
│   └── {session_prefix}_metadata.csv
└── camera2/
    ├── {session_prefix}.avi
    ├── {session_prefix}_timing.csv
    └── {session_prefix}_metadata.csv
```
