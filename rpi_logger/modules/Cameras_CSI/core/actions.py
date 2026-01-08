from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import CameraSettings, CameraCapabilities, FrameMetrics


@dataclass(frozen=True)
class AssignCamera:
    camera_index: int


@dataclass(frozen=True)
class CameraAssigned:
    camera_id: str
    camera_index: int
    capabilities: CameraCapabilities


@dataclass(frozen=True)
class CameraError:
    message: str


@dataclass(frozen=True)
class UnassignCamera:
    pass


@dataclass(frozen=True)
class StartPreview:
    pass


@dataclass(frozen=True)
class StopPreview:
    pass


@dataclass(frozen=True)
class StartRecording:
    session_dir: Path
    trial: int


@dataclass(frozen=True)
class StopRecording:
    pass


@dataclass(frozen=True)
class RecordingStarted:
    pass


@dataclass(frozen=True)
class RecordingStopped:
    pass


@dataclass(frozen=True)
class ApplySettings:
    settings: CameraSettings


@dataclass(frozen=True)
class SettingsApplied:
    settings: CameraSettings


@dataclass(frozen=True)
class FrameReceived:
    timestamp: float
    recorded: bool


@dataclass(frozen=True)
class UpdateMetrics:
    metrics: FrameMetrics


@dataclass(frozen=True)
class PreviewFrameReady:
    frame_data: bytes


@dataclass(frozen=True)
class Shutdown:
    pass


Action = (
    AssignCamera | CameraAssigned | CameraError | UnassignCamera |
    StartPreview | StopPreview |
    StartRecording | StopRecording | RecordingStarted | RecordingStopped |
    ApplySettings | SettingsApplied |
    FrameReceived | UpdateMetrics | PreviewFrameReady |
    Shutdown
)
