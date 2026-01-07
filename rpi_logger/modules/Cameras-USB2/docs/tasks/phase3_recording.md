# Phase 3: Recording

## Quick Reference

| Task | Status | Dependencies | Effort | Spec |
|------|--------|--------------|--------|------|
| P3.1 Session path resolution | available | P1.2 | Small | `specs/output_formats.md` |
| P3.2 Encoder integration | available | P2.3 | Medium | `specs/output_formats.md` |
| P3.3 Timing CSV writer | available | P3.2 | Small | `specs/output_formats.md` |
| P3.4 Disk guard integration | available | P3.1 | Small | `reference/mission.md` |

## Goal

Implement recording pipeline with precise timing and disk safety.

---

## P3.1: Session Path Resolution

### Deliverables

| File | Contents |
|------|----------|
| `storage/__init__.py` | Re-exports |
| `storage/session_paths.py` | Path resolution |

### Implementation

```python
# storage/session_paths.py
from dataclasses import dataclass
from pathlib import Path
import re

@dataclass
class SessionPaths:
    video_path: Path
    timing_path: Path
    metadata_path: Path
    output_dir: Path

def sanitize_label(label: str) -> str:
    # Replace non-alphanumeric with underscore, lowercase
    clean = re.sub(r'[^a-zA-Z0-9]+', '_', label)
    return clean.lower().strip('_')

def resolve_session_paths(
    base_path: Path,
    session_prefix: str,
    camera_label: str,
    per_camera_subdir: bool = False
) -> SessionPaths:
    label = sanitize_label(camera_label)

    if per_camera_subdir:
        output_dir = base_path / label
    else:
        output_dir = base_path

    output_dir.mkdir(parents=True, exist_ok=True)

    if per_camera_subdir:
        video_path = output_dir / f"{session_prefix}.avi"
        timing_path = output_dir / f"{session_prefix}_timing.csv"
        metadata_path = output_dir / f"{session_prefix}_metadata.csv"
    else:
        video_path = output_dir / f"{session_prefix}_{label}.avi"
        timing_path = output_dir / f"{session_prefix}_{label}_timing.csv"
        metadata_path = output_dir / f"{session_prefix}_{label}_metadata.csv"

    return SessionPaths(
        video_path=video_path,
        timing_path=timing_path,
        metadata_path=metadata_path,
        output_dir=output_dir
    )
```

### Validation

- [ ] Paths sanitized (no special characters)
- [ ] Directories created if missing
- [ ] Per-camera subdir option works
- [ ] Returns all three paths

---

## P3.2: Encoder Integration

### Deliverables

Integration with base module `Encoder` class in `bridge.py`.

### Implementation

```python
# In CamerasRuntime (bridge.py)

async def start_recording(
    self,
    session_prefix: str,
    trial_number: int,
    output_dir: Path | None = None
) -> None:
    if self._recording:
        return

    # Resolve paths
    base = output_dir or self._config.storage.base_path
    paths = resolve_session_paths(
        base_path=base,
        session_prefix=session_prefix,
        camera_label=self._camera_name,
        per_camera_subdir=self._config.storage.per_camera_subdir
    )

    # Create encoder (from base module)
    self._encoder = Encoder(
        output_path=paths.video_path,
        width=self._record_width,
        height=self._record_height,
        fps=self._record_fps,
        codec="mjpeg",
        quality=self._config.record.jpeg_quality
    )

    # Open timing CSV
    self._timing_writer = TimingCSVWriter(paths.timing_path, trial_number)

    # Store paths for metadata
    self._current_paths = paths
    self._trial_number = trial_number
    self._recording_start = time.time()
    self._frames_recorded = 0

    self._recording = True

    # Report status
    await self._report_status("recording_started", {
        "video_path": str(paths.video_path),
        "timing_path": str(paths.timing_path)
    })

async def stop_recording(self) -> None:
    if not self._recording:
        return

    self._recording = False

    # Flush and close encoder
    if self._encoder:
        await asyncio.to_thread(self._encoder.close)
        self._encoder = None

    # Close timing CSV
    if self._timing_writer:
        self._timing_writer.close()
        self._timing_writer = None

    # Write metadata
    if self._current_paths:
        await self._write_metadata()

    # Calculate stats
    duration = time.time() - self._recording_start
    actual_fps = self._frames_recorded / duration if duration > 0 else 0

    await self._report_status("recording_stopped", {
        "frames_recorded": self._frames_recorded,
        "duration_seconds": round(duration, 2),
        "actual_fps": round(actual_fps, 2)
    })
```

### Validation

- [ ] Encoder created with correct settings
- [ ] Recording starts/stops cleanly
- [ ] Status messages sent
- [ ] Files created at expected paths

---

## P3.3: Timing CSV Writer

### Deliverables

| File | Contents |
|------|----------|
| `storage/timing_writer.py` | TimingCSVWriter class |

### Implementation

```python
# storage/timing_writer.py
import csv
from pathlib import Path
from ..camera_core.types import CaptureFrame

class TimingCSVWriter:
    COLUMNS = [
        "trial",
        "module",
        "device_id",
        "label",
        "record_time_unix",
        "record_time_mono",
        "frame_index",
        "sensor_timestamp_ns",
        "video_pts"
    ]

    def __init__(
        self,
        path: Path,
        trial_number: int,
        device_id: str = "",
        label: str = ""
    ):
        self._path = path
        self._trial = trial_number
        self._device_id = device_id
        self._label = label
        self._file = open(path, 'w', newline='')
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.COLUMNS)
        self._pts = 0
        self._pts_increment = 0

    def set_fps(self, fps: float) -> None:
        # PTS increment in microseconds
        self._pts_increment = int(1_000_000 / fps)

    def write_frame(self, frame: CaptureFrame) -> None:
        row = [
            self._trial,
            "Cameras-USB2",
            self._device_id,
            self._label,
            f"{frame.timestamp_unix:.6f}",
            f"{frame.timestamp_mono:.9f}",
            frame.frame_index,
            0,  # No hardware timestamp for USB
            self._pts
        ]
        self._writer.writerow(row)
        self._pts += self._pts_increment

    def close(self) -> None:
        self._file.close()
```

### Validation

- [ ] CSV header matches schema
- [ ] Timestamps have correct precision
- [ ] PTS increments correctly
- [ ] File closes cleanly

---

## P3.4: Disk Guard Integration

### Deliverables

Integration with base module `DiskGuard` in `bridge.py`.

### Implementation

```python
# In CamerasRuntime (bridge.py)

async def _init_disk_guard(self) -> None:
    from rpi_logger.modules.base import DiskGuard

    self._disk_guard = DiskGuard(
        path=self._config.storage.base_path,
        min_free_gb=self._config.guard.disk_free_gb_min,
        check_interval_ms=self._config.guard.check_interval_ms,
        on_low_disk=self._handle_low_disk
    )
    await self._disk_guard.start()

async def _handle_low_disk(self, free_gb: float) -> None:
    # Stop recording if active
    if self._recording:
        await self.stop_recording()

    await self._report_status("disk_low", {
        "free_gb": round(free_gb, 2),
        "min_required_gb": self._config.guard.disk_free_gb_min
    })

async def _shutdown_disk_guard(self) -> None:
    if self._disk_guard:
        await self._disk_guard.stop()
        self._disk_guard = None
```

### Validation

- [ ] DiskGuard monitors storage path
- [ ] Recording stops when disk low
- [ ] Status message sent on low disk
- [ ] Guard stops cleanly on shutdown
