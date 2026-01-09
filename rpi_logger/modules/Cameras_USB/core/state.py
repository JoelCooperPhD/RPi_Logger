from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any


FRAME_RATE_OPTIONS = [1, 2, 5, 10, 15, 30]
PREVIEW_DIVISOR_OPTIONS = [2, 4, 8]
SAMPLE_RATE_OPTIONS = [22050, 44100, 48000]


class CameraPhase(Enum):
    IDLE = auto()
    DISCOVERING = auto()
    PROBING = auto()
    VERIFYING = auto()
    READY = auto()
    STREAMING = auto()
    ERROR = auto()


class AudioPhase(Enum):
    DISABLED = auto()
    UNAVAILABLE = auto()
    PROBING = auto()
    AVAILABLE = auto()
    CAPTURING = auto()
    ERROR = auto()


class RecordingPhase(Enum):
    STOPPED = auto()
    STARTING = auto()
    RECORDING = auto()
    STOPPING = auto()


@dataclass(frozen=True)
class USBDeviceInfo:
    device: int | str
    stable_id: str
    display_name: str
    vid_pid: str = ""
    sysfs_path: str = ""
    bus_path: str = ""

    @property
    def dev_path(self) -> str:
        return str(self.device) if isinstance(self.device, int) else self.device


@dataclass(frozen=True)
class USBAudioDevice:
    card_index: int
    device_name: str
    bus_path: str
    channels: int
    sample_rates: tuple[int, ...]
    sounddevice_index: int


@dataclass(frozen=True)
class CameraFingerprint:
    vid_pid: str
    capability_hash: str


@dataclass(frozen=True)
class CameraCapabilities:
    camera_id: str
    modes: tuple[dict[str, Any], ...] = ()
    controls: dict[str, tuple[Any, Any, Any]] = field(default_factory=dict)
    default_resolution: tuple[int, int] = (640, 480)
    default_fps: float = 30.0


@dataclass(frozen=True)
class CameraSettings:
    resolution: tuple[int, int] = (640, 480)
    frame_rate: int = 30
    preview_divisor: int = 4
    preview_scale: float = 0.25
    audio_mode: str = "auto"  # auto, on, off
    sample_rate: int = 48000

    @property
    def preview_fps(self) -> int:
        return max(1, self.frame_rate // self.preview_divisor)


@dataclass(frozen=True)
class CameraSlot:
    phase: CameraPhase = CameraPhase.IDLE
    device_info: USBDeviceInfo | None = None
    capabilities: CameraCapabilities | None = None
    fingerprint: CameraFingerprint | None = None
    model_key: str | None = None
    is_known: bool = False
    probing_progress: str = ""
    error_message: str | None = None


@dataclass(frozen=True)
class AudioSlot:
    phase: AudioPhase = AudioPhase.UNAVAILABLE
    device: USBAudioDevice | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class FrameMetrics:
    frames_captured: int = 0
    frames_recorded: int = 0
    frames_previewed: int = 0
    frames_dropped: int = 0
    audio_chunks_captured: int = 0
    last_frame_time: float = 0.0
    capture_fps_actual: float = 0.0
    record_fps_actual: float = 0.0
    preview_fps_actual: float = 0.0


@dataclass(frozen=True)
class AppState:
    camera: CameraSlot = field(default_factory=CameraSlot)
    audio: AudioSlot = field(default_factory=AudioSlot)
    recording_phase: RecordingPhase = RecordingPhase.STOPPED
    settings: CameraSettings = field(default_factory=CameraSettings)
    metrics: FrameMetrics = field(default_factory=FrameMetrics)
    session_dir: Path | None = None
    trial_number: int = 0
    preview_frame: bytes | None = None


def initial_state(
    frame_rate: int = 30,
    preview_scale: float = 0.25,
    preview_divisor: int = 4,
    audio_mode: str = "auto",
) -> AppState:
    return AppState(
        settings=CameraSettings(
            frame_rate=frame_rate,
            preview_scale=preview_scale,
            preview_divisor=preview_divisor,
            audio_mode=audio_mode,
        )
    )
