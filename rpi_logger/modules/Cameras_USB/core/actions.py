from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import (
    USBDeviceInfo, USBAudioDevice, CameraCapabilities,
    CameraFingerprint, CameraSettings, FrameMetrics
)


# Discovery actions

@dataclass(frozen=True)
class AssignDevice:
    dev_path: str
    stable_id: str
    vid_pid: str
    display_name: str
    sysfs_path: str
    bus_path: str


@dataclass(frozen=True)
class DeviceDiscovered:
    device_info: USBDeviceInfo
    cached_model_key: str | None
    cached_fingerprint: str | None


# Probing actions

@dataclass(frozen=True)
class StartProbing:
    reason: str  # "unknown_camera" | "fingerprint_mismatch"


@dataclass(frozen=True)
class ProbingProgress:
    message: str


@dataclass(frozen=True)
class VideoProbingComplete:
    capabilities: CameraCapabilities


@dataclass(frozen=True)
class AudioProbingComplete:
    audio_device: USBAudioDevice | None


@dataclass(frozen=True)
class ProbingFailed:
    error: str


# Fingerprint actions

@dataclass(frozen=True)
class FingerprintComputed:
    fingerprint: CameraFingerprint


@dataclass(frozen=True)
class QuickVerifyComplete:
    model_key: str
    capabilities: CameraCapabilities


@dataclass(frozen=True)
class QuickVerifyFailed:
    error: str


# Cache actions

@dataclass(frozen=True)
class StoreKnownCamera:
    stable_id: str
    model_key: str
    fingerprint: str
    capabilities: CameraCapabilities


# Camera lifecycle

@dataclass(frozen=True)
class CameraReady:
    is_known: bool


@dataclass(frozen=True)
class StartStreaming:
    pass


@dataclass(frozen=True)
class StreamingStarted:
    pass


@dataclass(frozen=True)
class StopStreaming:
    pass


@dataclass(frozen=True)
class CameraError:
    message: str


@dataclass(frozen=True)
class UnassignCamera:
    pass


# Audio actions

@dataclass(frozen=True)
class SetAudioMode:
    mode: str  # "auto" | "on" | "off"


@dataclass(frozen=True)
class AudioDeviceMatched:
    device: USBAudioDevice


@dataclass(frozen=True)
class StartAudioCapture:
    pass


@dataclass(frozen=True)
class AudioCaptureStarted:
    pass


@dataclass(frozen=True)
class StopAudioCapture:
    pass


@dataclass(frozen=True)
class AudioError:
    message: str


# Recording actions

@dataclass(frozen=True)
class StartRecording:
    session_dir: Path
    trial: int


@dataclass(frozen=True)
class RecordingStarted:
    pass


@dataclass(frozen=True)
class StopRecording:
    pass


@dataclass(frozen=True)
class RecordingStopped:
    pass


# Settings actions

@dataclass(frozen=True)
class ApplySettings:
    settings: CameraSettings


@dataclass(frozen=True)
class SettingsApplied:
    settings: CameraSettings


# Metrics and preview

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
    AssignDevice | DeviceDiscovered |
    StartProbing | ProbingProgress | VideoProbingComplete | AudioProbingComplete | ProbingFailed |
    FingerprintComputed | QuickVerifyComplete | QuickVerifyFailed |
    StoreKnownCamera |
    CameraReady | StartStreaming | StreamingStarted | StopStreaming | CameraError | UnassignCamera |
    SetAudioMode | AudioDeviceMatched | StartAudioCapture | AudioCaptureStarted | StopAudioCapture | AudioError |
    StartRecording | RecordingStarted | StopRecording | RecordingStopped |
    ApplySettings | SettingsApplied |
    UpdateMetrics | PreviewFrameReady |
    Shutdown
)
