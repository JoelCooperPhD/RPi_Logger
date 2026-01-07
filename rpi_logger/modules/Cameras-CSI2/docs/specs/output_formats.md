# Output Format Specification

> Video and CSV output formats

## Directory Structure

**MUST MATCH CURRENT MODULE**

```
{session_dir}/
└── CSICameras/
    └── {camera_label}/
        ├── {prefix}_{camera_label}.avi
        └── {prefix}_{camera_label}_timing.csv
```

Where:
- `session_dir`: Provided by parent logger (e.g., `/data/session_20260106_081726/`)
- `camera_label`: `{sanitized_friendly_name}_{stable_id_first_8}` (e.g., `IMX296_Global_picam_0`)
- `prefix`: `{session_token}_{MODULE_CODE}_trial{NNN}` (e.g., `20260106_081726_CSI_trial001`)

---

## Video Format

**MUST MATCH CURRENT MODULE**

| Property | Value |
|----------|-------|
| Container | AVI |
| Codec | MJPEG (Motion JPEG) |
| Quality | 85 (configurable) |
| Resolution | Full sensor resolution (not configurable) |
| Frame rate | As specified in settings |

**Note**: Pi 5 has NO hardware H.264 encoder. MJPEG is the only option.

---

## Timing CSV Format

**MUST MATCH CURRENT MODULE**

### Header Row

```
trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,sensor_timestamp_ns,video_pts
```

### Data Row Example

```
1,CSICameras,picam:0,,1767748502.723745,156789.123456789,1,1234567890123456,1
```

### Column Specifications

| Column | Type | Format | Source |
|--------|------|--------|--------|
| `trial` | int | `%d` | Trial number |
| `module` | str | literal | "CSICameras" |
| `device_id` | str | `%s` | Camera key |
| `label` | str | `%s` | Trial label (may be empty) |
| `record_time_unix` | float | `%.6f` | `frame.wall_time` |
| `record_time_mono` | float | `%.9f` | `frame.monotonic_ns / 1e9` |
| `frame_index` | int | `%d` | 1-based frame number in recording |
| `sensor_timestamp_ns` | int | `%d` | `frame.sensor_timestamp_ns` |
| `video_pts` | int | `%d` | Same as frame_index |

---

## TimingCSVWriter Implementation

```python
class TimingCSVWriter:
    HEADER = "trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,sensor_timestamp_ns,video_pts\n"

    def __init__(self, path: Path, trial_number: int, device_id: str):
        self._file = open(path, 'w', newline='')
        self._file.write(self.HEADER)
        self._trial = trial_number
        self._device_id = device_id
        self._label = ""

    def write_frame(self, frame: CapturedFrame, frame_index: int) -> None:
        row = f"{self._trial},CSICameras,{self._device_id},{self._label},"
        row += f"{frame.wall_time:.6f},{frame.monotonic_ns / 1e9:.9f},"
        row += f"{frame_index},{frame.sensor_timestamp_ns},{frame_index}\n"
        self._file.write(row)

    def close(self) -> None:
        self._file.close()
```

---

## Validation

To verify output format compatibility:

```bash
# Compare headers byte-for-byte
head -1 old_timing.csv > /tmp/old_header
head -1 new_timing.csv > /tmp/new_header
diff /tmp/old_header /tmp/new_header

# Should produce no output (headers identical)
```
