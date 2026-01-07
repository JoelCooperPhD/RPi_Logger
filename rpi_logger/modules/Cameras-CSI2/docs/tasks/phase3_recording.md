# Phase 3: Recording

> Video and CSV output pipeline

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Sub-tasks** | P3.1, P3.2, P3.3, P3.4 |
| **Dependencies** | P1.1, P2.1, P3.1, P3.2 |
| **Effort** | Medium |
| **Key Specs** | [output_formats.md](../specs/output_formats.md) |

## Goal

Write video (MJPEG/AVI) and timing CSV that match current module output exactly.

---

## Sub-Tasks

### P3.1: TimingCSVWriter

**File**: `recording/timing_csv.py` (~60 lines)

**Output columns MUST MATCH exactly**:
```csv
trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,sensor_timestamp_ns,video_pts
```

```python
class TimingCSVWriter:
    def __init__(self, path: Path, trial_number: int, device_id: str): ...
    def write_frame(self, frame: CapturedFrame, frame_index: int) -> None: ...
    def close(self) -> None: ...
```

**Column formats**:
- `record_time_unix`: `%.6f`
- `record_time_mono`: `%.9f`
- `frame_index`: 1-based
- `sensor_timestamp_ns`: integer (nanoseconds)

---

### P3.2: VideoEncoder

**File**: `recording/encoder.py` (~80 lines)

Wraps picamera2's MJPEG encoder.

```python
class VideoEncoder:
    def __init__(self, path: Path, quality: int = 85): ...
    async def start(self) -> None: ...
    async def write_frame(self, frame: CapturedFrame) -> None: ...
    async def stop(self) -> dict: ...  # Returns metrics
```

**Uses**: `JpegEncoder` + `FfmpegOutput` for AVI container

**Note**: Pi 5 has NO hardware H.264 encoder. MJPEG only.

---

### P3.3: RecordingSession

**File**: `recording/recorder.py` (~100 lines)

Manages recording lifecycle.

```python
class RecordingSession:
    def __init__(self, gate: TimingGate): ...
    async def start(self, session_dir: Path, trial_number: int, camera_id: CameraId) -> None: ...
    async def stop(self) -> RecordingMetrics: ...
    async def write_frame(self, frame: CapturedFrame) -> None: ...

    @property
    def is_recording(self) -> bool: ...
    @property
    def frame_count(self) -> int: ...
```

Coordinates encoder + CSV writer, handles paths.

---

### P3.4: Session Paths

**File**: `recording/session_paths.py` (~50 lines)

Can copy from current module: `/home/rs-pi-2/Development/Logger/rpi_logger/modules/CSICameras/storage/session_paths.py`

**Output structure**:
```
{session_dir}/
└── CSICameras/
    └── {camera_label}/
        ├── {prefix}_{camera_label}.avi
        └── {prefix}_{camera_label}_timing.csv
```

---

## Validation Checklist

- [ ] All 4 files created
- [ ] CSV header matches exactly (compare byte-for-byte)
- [ ] Video format is MJPEG/AVI
- [ ] Integration test: Record 10 seconds, compare to current module output

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md).
