from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

FRAME_RATE_OPTIONS = [1, 2, 5, 10, 15, 30]
PREVIEW_DIVISOR_OPTIONS = [2, 4, 8]
SAMPLE_RATE_OPTIONS = [22050, 44100, 48000]


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
    # Camera flags (replaces CameraPhase enum)
    assigned: bool = False
    probing: bool = False
    ready: bool = False
    streaming: bool = False
    camera_error: Optional[str] = None

    # Camera data
    device_info: Optional[USBDeviceInfo] = None
    capabilities: Optional[CameraCapabilities] = None
    probing_progress: str = ""

    # Audio flags (replaces AudioPhase enum)
    audio_enabled: bool = True
    audio_available: bool = False
    audio_capturing: bool = False
    audio_error: Optional[str] = None
    audio_device: Optional[USBAudioDevice] = None

    # Recording flags (replaces RecordingPhase enum)
    recording: bool = False

    # Settings and metrics
    settings: CameraSettings = field(default_factory=CameraSettings)
    metrics: FrameMetrics = field(default_factory=FrameMetrics)
    session_dir: Optional[Path] = None
    trial_number: int = 0
    preview_frame: Optional[bytes] = None

    @property
    def can_stream(self) -> bool:
        return self.ready and not self.streaming and not self.camera_error

    @property
    def can_record(self) -> bool:
        return self.streaming and not self.recording

    @property
    def phase_display(self) -> str:
        if self.camera_error:
            return "Error"
        if self.recording:
            return "Recording"
        if self.streaming:
            return "Streaming"
        if self.probing:
            return "Probing"
        if self.ready:
            return "Ready"
        if self.assigned:
            return "Assigned"
        return "Idle"
