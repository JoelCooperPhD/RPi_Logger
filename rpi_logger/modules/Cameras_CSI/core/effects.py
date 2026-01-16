from dataclasses import dataclass
from pathlib import Path

from .state import CameraSettings


@dataclass(frozen=True)
class ProbeCamera:
    camera_index: int


@dataclass(frozen=True)
class OpenCamera:
    camera_index: int
    settings: CameraSettings


@dataclass(frozen=True)
class CloseCamera:
    pass


@dataclass(frozen=True)
class StartCapture:
    pass


@dataclass(frozen=True)
class StopCapture:
    pass


@dataclass(frozen=True)
class StartEncoder:
    output_path: Path
    fps: int
    resolution: tuple[int, int]
    label: str = ""


@dataclass(frozen=True)
class StopEncoder:
    pass


@dataclass(frozen=True)
class StartTimingWriter:
    output_path: Path


@dataclass(frozen=True)
class StopTimingWriter:
    pass


@dataclass(frozen=True)
class ApplyCameraSettings:
    settings: CameraSettings


@dataclass(frozen=True)
class SendStatus:
    status_type: str
    payload: dict


@dataclass(frozen=True)
class CleanupResources:
    pass


Effect = (
    ProbeCamera | OpenCamera | CloseCamera |
    StartCapture | StopCapture |
    StartEncoder | StopEncoder |
    StartTimingWriter | StopTimingWriter |
    ApplyCameraSettings |
    SendStatus | CleanupResources
)
