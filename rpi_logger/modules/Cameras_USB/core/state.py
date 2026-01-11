from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional

FRAME_RATE_OPTIONS = [1, 2, 5, 10, 15, 30]
PREVIEW_DIVISOR_OPTIONS = [1, 2, 4, 8]
SAMPLE_RATE_OPTIONS = [22050, 44100, 48000]


class CameraPhase(Enum):
    IDLE = auto()
    PROBING = auto()
    READY = auto()
    STREAMING = auto()
    ERROR = auto()


class RecordingPhase(Enum):
    STOPPED = auto()
    RECORDING = auto()


class AudioPhase(Enum):
    IDLE = auto()
    CAPTURING = auto()


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
    audio_mode: str = "auto"
    sample_rate: int = 48000

    @property
    def preview_fps(self) -> int:
        return max(1, self.frame_rate // self.preview_divisor)


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


@dataclass
class CameraState:
    phase: CameraPhase = CameraPhase.IDLE
    error_message: str = ""
    recording_phase: RecordingPhase = RecordingPhase.STOPPED
    audio_phase: AudioPhase = AudioPhase.IDLE

    device_info: Optional[USBDeviceInfo] = None
    capabilities: Optional[CameraCapabilities] = None
    probing_progress: str = ""
    audio_device: Optional[USBAudioDevice] = None

    settings: CameraSettings = field(default_factory=CameraSettings)
    metrics: FrameMetrics = field(default_factory=FrameMetrics)
    session_dir: Optional[Path] = None
    trial_number: int = 0
    preview_frame: Optional[bytes] = None

    @property
    def can_stream(self) -> bool:
        return self.phase == CameraPhase.READY

    @property
    def can_record(self) -> bool:
        return self.phase == CameraPhase.STREAMING and self.recording_phase == RecordingPhase.STOPPED

    @property
    def phase_display(self) -> str:
        if self.phase == CameraPhase.ERROR:
            return "Error"
        if self.recording_phase == RecordingPhase.RECORDING:
            return "Recording"
        return self.phase.name.capitalize()

    @property
    def audio_available(self) -> bool:
        return self.audio_device is not None

    @property
    def audio_enabled(self) -> bool:
        return self.settings.audio_mode != "off"

    @property
    def audio_capturing(self) -> bool:
        return self.audio_phase == AudioPhase.CAPTURING

    @property
    def assigned(self) -> bool:
        return self.phase != CameraPhase.IDLE

    @property
    def probing(self) -> bool:
        return self.phase == CameraPhase.PROBING

    @property
    def ready(self) -> bool:
        return self.phase == CameraPhase.READY

    @property
    def streaming(self) -> bool:
        return self.phase == CameraPhase.STREAMING

    @property
    def recording(self) -> bool:
        return self.recording_phase == RecordingPhase.RECORDING

    @property
    def has_error(self) -> bool:
        return self.phase == CameraPhase.ERROR
