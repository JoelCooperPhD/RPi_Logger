# Core types for Cameras-USB2 module
# Task: P1.1
from dataclasses import dataclass, field
import time

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
    modes: list[CapabilityMode] = field(default_factory=list)
    controls: dict[str, ControlInfo] = field(default_factory=dict)
    default_preview: CapabilityMode | None = None
    default_record: CapabilityMode | None = None
    probed_at: float = field(default_factory=time.time)
