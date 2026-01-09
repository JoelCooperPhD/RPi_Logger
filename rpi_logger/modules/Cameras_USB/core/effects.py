"""Effects for USB camera module.

Effects are side-effects that the reducer requests to be performed.
The effect executor handles these asynchronously.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import CameraSettings


# Camera setup effects

@dataclass(frozen=True)
class EnsureCameraProbed:
    """Ensure camera capabilities are known (probe if needed)."""
    device: int | str
    vid_pid: str
    display_name: str


@dataclass(frozen=True)
class ProbeAudio:
    """Find matching audio device for the camera."""
    bus_path: str


# Camera operation effects

@dataclass(frozen=True)
class OpenCamera:
    """Open camera for capture."""
    device: int | str
    resolution: tuple[int, int]
    fps: float


@dataclass(frozen=True)
class CloseCamera:
    """Close camera."""
    pass


@dataclass(frozen=True)
class StartCapture:
    """Start frame capture loop."""
    pass


@dataclass(frozen=True)
class StopCapture:
    """Stop frame capture loop."""
    pass


@dataclass(frozen=True)
class ApplyCameraSettings:
    """Apply new settings to camera."""
    settings: CameraSettings


# Audio effects

@dataclass(frozen=True)
class OpenAudioDevice:
    """Open audio device for capture."""
    sounddevice_index: int
    sample_rate: int
    channels: int
    supported_rates: tuple[int, ...] = ()


@dataclass(frozen=True)
class CloseAudioDevice:
    """Close audio device."""
    pass


@dataclass(frozen=True)
class StartAudioStream:
    """Start audio capture."""
    pass


@dataclass(frozen=True)
class StopAudioStream:
    """Stop audio capture."""
    pass


# Recording effects

@dataclass(frozen=True)
class StartEncoder:
    """Start video encoder."""
    video_path: Path
    fps: int
    resolution: tuple[int, int]
    with_audio: bool


@dataclass(frozen=True)
class StopEncoder:
    """Stop video encoder."""
    pass


@dataclass(frozen=True)
class StartMuxer:
    """Start audio/video muxer."""
    output_path: Path
    video_fps: int
    resolution: tuple[int, int]
    audio_sample_rate: int
    audio_channels: int


@dataclass(frozen=True)
class StopMuxer:
    """Stop muxer."""
    pass


@dataclass(frozen=True)
class StartTimingWriter:
    """Start timing file writer."""
    output_path: Path


@dataclass(frozen=True)
class StopTimingWriter:
    """Stop timing file writer."""
    pass


# Status effects

@dataclass(frozen=True)
class SendStatus:
    """Send status to parent process."""
    status_type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class CleanupResources:
    """Clean up all resources on shutdown."""
    pass


Effect = (
    EnsureCameraProbed | ProbeAudio |
    OpenCamera | CloseCamera | StartCapture | StopCapture | ApplyCameraSettings |
    OpenAudioDevice | CloseAudioDevice | StartAudioStream | StopAudioStream |
    StartEncoder | StopEncoder | StartMuxer | StopMuxer | StartTimingWriter | StopTimingWriter |
    SendStatus | CleanupResources
)
