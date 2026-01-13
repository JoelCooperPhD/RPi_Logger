"""State definitions for USB camera module."""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional


class Phase(Enum):
    """Camera lifecycle phase."""

    IDLE = auto()
    STARTING = auto()
    STREAMING = auto()
    ERROR = auto()


class RecordingPhase(Enum):
    """Recording state."""

    STOPPED = auto()
    RECORDING = auto()


@dataclass(frozen=True)
class Settings:
    """User settings - immutable."""

    resolution: tuple[int, int] = (640, 480)
    frame_rate: int = 30  # Target record/display rate
    preview_divisor: int = 4  # Preview at frame_rate / divisor
    preview_scale: float = 0.25  # Preview image scale
    audio_enabled: bool = False
    audio_device_index: Optional[int] = None
    sample_rate: int = 48000
    audio_channels: int = 1


@dataclass(frozen=True)
class Metrics:
    """Runtime metrics - immutable snapshot."""

    hardware_fps: float = 0.0  # What camera actually delivers
    record_fps: float = 0.0  # Actual recording rate
    preview_fps: float = 0.0  # Actual preview rate
    frames_captured: int = 0  # Total from hardware
    frames_recorded: int = 0  # Written to video
    frames_dropped: int = 0  # Buffer overflows
    audio_chunks: int = 0  # Audio chunks captured


@dataclass
class CameraState:
    """Mutable camera state."""

    phase: Phase = Phase.IDLE
    recording_phase: RecordingPhase = RecordingPhase.STOPPED
    settings: Settings = field(default_factory=Settings)
    metrics: Metrics = field(default_factory=Metrics)
    error: str = ""
    session_dir: Optional[Path] = None
    trial_number: int = 0
    device_name: str = ""
    has_audio: bool = False
