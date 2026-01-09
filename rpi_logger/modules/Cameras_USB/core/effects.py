from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import CameraSettings, CameraCapabilities


# Discovery effects

@dataclass(frozen=True)
class LookupKnownCamera:
    stable_id: str
    vid_pid: str


@dataclass(frozen=True)
class ProbeVideoCapabilities:
    device: int | str


@dataclass(frozen=True)
class QuickVerifyCamera:
    device: int | str
    cached_model_key: str
    cached_fingerprint: str


@dataclass(frozen=True)
class ProbeAudioCapabilities:
    bus_path: str


# Fingerprint effects

@dataclass(frozen=True)
class ComputeFingerprint:
    vid_pid: str
    capabilities: CameraCapabilities


# Cache effects

@dataclass(frozen=True)
class PersistKnownCamera:
    stable_id: str
    model_key: str
    fingerprint: str
    capabilities: CameraCapabilities


@dataclass(frozen=True)
class LoadCachedSettings:
    stable_id: str


@dataclass(frozen=True)
class PersistSettings:
    stable_id: str
    settings: dict[str, str]


# Camera effects

@dataclass(frozen=True)
class OpenCamera:
    device: int | str
    resolution: tuple[int, int]
    fps: float


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
class ApplyCameraSettings:
    settings: CameraSettings


# Audio effects

@dataclass(frozen=True)
class OpenAudioDevice:
    sounddevice_index: int
    sample_rate: int
    channels: int
    supported_rates: tuple[int, ...] = ()


@dataclass(frozen=True)
class CloseAudioDevice:
    pass


@dataclass(frozen=True)
class StartAudioStream:
    pass


@dataclass(frozen=True)
class StopAudioStream:
    pass


# Recording effects

@dataclass(frozen=True)
class StartEncoder:
    video_path: Path
    fps: int
    resolution: tuple[int, int]
    with_audio: bool


@dataclass(frozen=True)
class StopEncoder:
    pass


@dataclass(frozen=True)
class StartMuxer:
    output_path: Path
    video_fps: int
    resolution: tuple[int, int]
    audio_sample_rate: int
    audio_channels: int


@dataclass(frozen=True)
class StopMuxer:
    pass


@dataclass(frozen=True)
class StartTimingWriter:
    output_path: Path


@dataclass(frozen=True)
class StopTimingWriter:
    pass


# Status effects

@dataclass(frozen=True)
class SendStatus:
    status_type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class NotifyUI:
    event: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class CleanupResources:
    pass


Effect = (
    LookupKnownCamera | ProbeVideoCapabilities | QuickVerifyCamera | ProbeAudioCapabilities |
    ComputeFingerprint | PersistKnownCamera | LoadCachedSettings | PersistSettings |
    OpenCamera | CloseCamera | StartCapture | StopCapture | ApplyCameraSettings |
    OpenAudioDevice | CloseAudioDevice | StartAudioStream | StopAudioStream |
    StartEncoder | StopEncoder | StartMuxer | StopMuxer | StartTimingWriter | StopTimingWriter |
    SendStatus | NotifyUI | CleanupResources
)
