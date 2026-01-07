# Phase 1: Foundation

## Quick Reference

| Task | Status | Dependencies | Effort | Spec |
|------|--------|--------------|--------|------|
| P1.1 Core types | available | - | Small | `specs/components.md` |
| P1.2 Config system | available | - | Medium | `specs/components.md` |
| P1.3 USB backend probe | available | P1.1 | Medium | `specs/components.md` |
| P1.4 Capability normalization | available | P1.1, P1.3 | Small | `specs/components.md` |

## Goal

Establish core types, configuration, and camera discovery infrastructure.

---

## P1.1: Core Types and Interfaces

### Deliverables

| File | Contents |
|------|----------|
| `camera_core/__init__.py` | Re-export public types |
| `camera_core/types.py` | Core dataclasses |

### Implementation

Create shared types used throughout module:

```python
# camera_core/types.py
from dataclasses import dataclass

@dataclass(frozen=True)
class CameraId:
    backend: str
    stable_id: str
    def __str__(self) -> str:
        return f"{self.backend}:{self.stable_id}"

@dataclass
class CameraDescriptor:
    camera_id: CameraId
    name: str
    device_path: str
    usb_path: str | None = None

@dataclass
class CaptureFrame:
    data: bytes
    timestamp_mono: float
    timestamp_unix: float
    frame_index: int
    width: int
    height: int

@dataclass
class CapabilityMode:
    width: int
    height: int
    fps: float
    pixel_format: str

@dataclass
class ControlInfo:
    name: str
    control_type: str
    min_value: int | None = None
    max_value: int | None = None
    default_value: int | None = None
    step: int | None = None
    menu_items: dict[int, str] | None = None

@dataclass
class CameraCapabilities:
    modes: list[CapabilityMode]
    controls: dict[str, ControlInfo]
    default_preview: CapabilityMode | None = None
    default_record: CapabilityMode | None = None
    probed_at: float = 0.0
```

### Validation

- [ ] All types importable from `camera_core`
- [ ] Type hints pass `mypy --strict`
- [ ] `CameraId` is hashable (frozen)

---

## P1.2: Configuration System

### Deliverables

| File | Contents |
|------|----------|
| `config.py` | Configuration dataclasses and loaders |
| `config.txt` | Default configuration template |

### Implementation

```python
# config.py
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class PreviewSettings:
    resolution: tuple[int, int] = (640, 480)
    fps_cap: int = 15
    pixel_format: str = "MJPG"
    overlay: bool = False

@dataclass
class RecordSettings:
    resolution: tuple[int, int] = (1280, 720)
    fps_cap: int = 30
    pixel_format: str = "MJPG"
    overlay: bool = True
    jpeg_quality: int = 80

@dataclass
class StorageSettings:
    base_path: Path = field(default_factory=lambda: Path.cwd())
    per_camera_subdir: bool = False

@dataclass
class GuardSettings:
    disk_free_gb_min: float = 1.0
    check_interval_ms: int = 5000

@dataclass
class CamerasConfig:
    preview: PreviewSettings = field(default_factory=PreviewSettings)
    record: RecordSettings = field(default_factory=RecordSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    guard: GuardSettings = field(default_factory=GuardSettings)
    log_level: str = "INFO"

    @classmethod
    def from_preferences(cls, prefs: dict, cli_overrides: dict | None = None) -> "CamerasConfig":
        # Implement preference loading with CLI override support
        ...

    def to_dict(self) -> dict:
        # Export flat dictionary
        ...
```

### Validation

- [ ] `CamerasConfig.from_preferences()` loads from dict
- [ ] CLI overrides take precedence
- [ ] `config.txt` parseable

---

## P1.3: USB Backend Probe

### Deliverables

| File | Contents |
|------|----------|
| `camera_core/backends/__init__.py` | Backend exports |
| `camera_core/backends/usb_backend.py` | USB probe implementation |

### Implementation

```python
# camera_core/backends/usb_backend.py
import asyncio
import subprocess
from ..types import CameraCapabilities, CapabilityMode, ControlInfo

class ProbeError(Exception):
    def __init__(self, device_path: str, reason: str):
        self.device_path = device_path
        self.reason = reason

class DeviceLost(Exception):
    def __init__(self, camera_id):
        self.camera_id = camera_id

async def probe(device_path: str) -> CameraCapabilities:
    modes = await _probe_modes(device_path)
    controls = await _probe_controls(device_path)
    return CameraCapabilities(
        modes=modes,
        controls=controls,
        probed_at=time.time()
    )

async def _probe_modes(device_path: str) -> list[CapabilityMode]:
    # Use v4l2-ctl --list-formats-ext via asyncio.to_thread
    cmd = ["v4l2-ctl", "-d", device_path, "--list-formats-ext"]
    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True
    )
    # Parse output into CapabilityMode list
    ...

async def _probe_controls(device_path: str) -> dict[str, ControlInfo]:
    # Use v4l2-ctl --list-ctrls-menus
    cmd = ["v4l2-ctl", "-d", device_path, "--list-ctrls-menus"]
    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True
    )
    # Parse output into ControlInfo dict
    ...

async def set_control(device_path: str, control: str, value: int) -> None:
    cmd = ["v4l2-ctl", "-d", device_path, "-c", f"{control}={value}"]
    await asyncio.to_thread(subprocess.run, cmd, check=True)

async def get_control(device_path: str, control: str) -> int:
    cmd = ["v4l2-ctl", "-d", device_path, "-C", control]
    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True
    )
    # Parse and return value
    ...
```

### Validation

- [ ] `probe("/dev/video0")` returns `CameraCapabilities`
- [ ] Non-blocking: no blocking calls in async functions
- [ ] `ProbeError` raised for invalid device
- [ ] Controls include brightness, contrast (if available)

---

## P1.4: Capability Normalization

### Deliverables

| File | Contents |
|------|----------|
| `camera_core/capabilities.py` | Normalization and defaults |

### Implementation

```python
# camera_core/capabilities.py
from .types import CameraCapabilities, CapabilityMode

def build_capabilities(raw_modes: list[CapabilityMode]) -> CameraCapabilities:
    modes = normalize_modes(raw_modes)
    return CameraCapabilities(
        modes=modes,
        controls={},
        default_preview=select_default_preview(modes),
        default_record=select_default_record(modes)
    )

def normalize_modes(modes: list[CapabilityMode]) -> list[CapabilityMode]:
    # Deduplicate, sort by resolution descending
    seen = set()
    result = []
    for m in modes:
        key = (m.width, m.height, m.fps, m.pixel_format)
        if key not in seen:
            seen.add(key)
            result.append(m)
    return sorted(result, key=lambda m: (m.width * m.height, m.fps), reverse=True)

def select_default_preview(modes: list[CapabilityMode]) -> CapabilityMode | None:
    # Max 640x480, prefer 15+ FPS, respect aspect ratio
    candidates = [m for m in modes if m.width <= 640 and m.height <= 480]
    if not candidates:
        return modes[0] if modes else None
    # Prefer modes with FPS >= 15
    preferred = [m for m in candidates if m.fps >= 15]
    return max(preferred or candidates, key=lambda m: m.width * m.height)

def select_default_record(modes: list[CapabilityMode]) -> CapabilityMode | None:
    # Highest 16:9, prefer 30 FPS
    ratio_16_9 = [m for m in modes if abs(m.width/m.height - 16/9) < 0.1]
    if ratio_16_9:
        # Prefer 30 FPS, then highest resolution
        at_30 = [m for m in ratio_16_9 if 29 <= m.fps <= 31]
        if at_30:
            return max(at_30, key=lambda m: m.width * m.height)
        return max(ratio_16_9, key=lambda m: m.width * m.height)
    return modes[0] if modes else None
```

### Validation

- [ ] `normalize_modes()` removes duplicates
- [ ] `select_default_preview()` returns mode <= 640x480
- [ ] `select_default_record()` prefers 16:9 at 30 FPS
- [ ] Handles empty mode list gracefully
