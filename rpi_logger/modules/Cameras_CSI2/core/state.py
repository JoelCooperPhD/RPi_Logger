from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any


class CameraStatus(Enum):
    IDLE = auto()
    ASSIGNING = auto()
    STREAMING = auto()
    ERROR = auto()


class RecordingStatus(Enum):
    STOPPED = auto()
    STARTING = auto()
    RECORDING = auto()
    STOPPING = auto()


@dataclass(frozen=True)
class CameraSettings:
    resolution: tuple[int, int] = (1920, 1080)
    capture_fps: int = 30
    preview_fps: int = 10
    preview_scale: float = 0.25  # 1/4 scale default
    record_fps: int = 5
    exposure_time: int | None = None
    analog_gain: float | None = None
    awb_mode: str = "auto"


@dataclass(frozen=True)
class CameraCapabilities:
    camera_id: str
    sensor_modes: tuple[dict[str, Any], ...] = ()
    controls: dict[str, tuple[Any, Any, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class FrameMetrics:
    frames_captured: int = 0
    frames_recorded: int = 0
    frames_previewed: int = 0
    frames_dropped: int = 0
    last_frame_time: float = 0.0
    capture_fps_actual: float = 0.0
    record_fps_actual: float = 0.0


@dataclass(frozen=True)
class AppState:
    camera_status: CameraStatus = CameraStatus.IDLE
    recording_status: RecordingStatus = RecordingStatus.STOPPED
    camera_id: str | None = None
    camera_index: int | None = None
    capabilities: CameraCapabilities | None = None
    settings: CameraSettings = field(default_factory=CameraSettings)
    metrics: FrameMetrics = field(default_factory=FrameMetrics)
    error_message: str | None = None
    session_dir: Path | None = None
    trial_number: int = 0
    preview_frame: bytes | None = None


def initial_state() -> AppState:
    return AppState()
