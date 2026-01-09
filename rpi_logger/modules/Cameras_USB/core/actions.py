"""Actions for USB camera state machine.

Simplified: No fingerprints, no quick-verify, just assign → probe if needed → ready.
"""

from dataclasses import dataclass
from pathlib import Path

from .state import (
    USBDeviceInfo, USBAudioDevice, CameraCapabilities,
    CameraSettings, FrameMetrics
)


# Camera lifecycle

@dataclass(frozen=True)
class AssignDevice:
    """Assign a USB camera device to this module."""
    dev_path: str
    stable_id: str
    vid_pid: str
    display_name: str
    sysfs_path: str
    bus_path: str


@dataclass(frozen=True)
class ProbingProgress:
    """Update probing status message."""
    message: str


@dataclass(frozen=True)
class CameraReady:
    """Camera is ready with capabilities loaded."""
    capabilities: CameraCapabilities


@dataclass(frozen=True)
class CameraError:
    """Camera encountered an error."""
    message: str


@dataclass(frozen=True)
class UnassignCamera:
    """Unassign the current camera."""
    pass


# Streaming

@dataclass(frozen=True)
class StartStreaming:
    """Start camera capture/preview."""
    pass


@dataclass(frozen=True)
class StreamingStarted:
    """Camera is now streaming."""
    pass


@dataclass(frozen=True)
class StopStreaming:
    """Stop camera capture/preview."""
    pass


# Audio

@dataclass(frozen=True)
class SetAudioMode:
    """Set audio capture mode."""
    mode: str  # "auto" | "on" | "off"


@dataclass(frozen=True)
class AudioReady:
    """Audio device matched and ready."""
    device: USBAudioDevice | None


@dataclass(frozen=True)
class AudioCaptureStarted:
    """Audio capture has started."""
    pass


@dataclass(frozen=True)
class AudioError:
    """Audio encountered an error."""
    message: str


# Recording

@dataclass(frozen=True)
class StartRecording:
    """Start recording video/audio."""
    session_dir: Path
    trial: int


@dataclass(frozen=True)
class RecordingStarted:
    """Recording has started."""
    pass


@dataclass(frozen=True)
class StopRecording:
    """Stop recording."""
    pass


@dataclass(frozen=True)
class RecordingStopped:
    """Recording has stopped."""
    pass


# Settings

@dataclass(frozen=True)
class ApplySettings:
    """Apply new camera settings."""
    settings: CameraSettings


@dataclass(frozen=True)
class SettingsApplied:
    """Settings have been applied."""
    settings: CameraSettings


# Metrics

@dataclass(frozen=True)
class UpdateMetrics:
    """Update frame metrics."""
    metrics: FrameMetrics


@dataclass(frozen=True)
class PreviewFrameReady:
    """New preview frame available."""
    frame_data: bytes


# Shutdown

@dataclass(frozen=True)
class Shutdown:
    """Shutdown the module."""
    pass


Action = (
    AssignDevice | ProbingProgress | CameraReady | CameraError | UnassignCamera |
    StartStreaming | StreamingStarted | StopStreaming |
    SetAudioMode | AudioReady | AudioCaptureStarted | AudioError |
    StartRecording | RecordingStarted | StopRecording | RecordingStopped |
    ApplySettings | SettingsApplied |
    UpdateMetrics | PreviewFrameReady |
    Shutdown
)
