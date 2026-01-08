from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

SENSOR_MAX_FPS = 60
FRAME_RATE_OPTIONS = [1, 2, 5, 15, 30, 60]
PREVIEW_DIVISOR_OPTIONS = [2, 4, 8]


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
    resolution: tuple[int, int] = (1456, 1088)  # IMX296 native
    frame_rate: int = 30  # Hardware capture AND recording rate
    preview_divisor: int = 4  # Preview = frame_rate / divisor
    preview_scale: float = 0.25  # 1/4 scale default
    exposure_time: int | None = None
    analog_gain: float | None = None
    awb_mode: str = "auto"

    @property
    def preview_fps(self) -> int:
        return max(1, self.frame_rate // self.preview_divisor)


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
    preview_fps_actual: float = 0.0


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


def initial_state(
    frame_rate: int = 30,
    preview_scale: float = 0.25,
    preview_divisor: int = 4,
) -> AppState:
    return AppState(
        settings=CameraSettings(
            frame_rate=frame_rate,
            preview_scale=preview_scale,
            preview_divisor=preview_divisor,
        )
    )
