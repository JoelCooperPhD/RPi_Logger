"""State definitions for USB camera module."""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional


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


# ---------------------------------------------------------------------------
# Settings Persistence Helpers
# ---------------------------------------------------------------------------


def settings_to_persistable(settings: Settings) -> dict[str, str]:
    """Convert Settings to dict for persistence.

    Args:
        settings: Settings object to serialize.

    Returns:
        Dict with string keys and values suitable for config file storage.
    """
    return {
        "resolution_width": str(settings.resolution[0]),
        "resolution_height": str(settings.resolution[1]),
        "frame_rate": str(settings.frame_rate),
        "preview_scale": str(settings.preview_scale),
        "preview_divisor": str(settings.preview_divisor),
        "audio_enabled": "true" if settings.audio_enabled else "false",
        "sample_rate": str(settings.sample_rate),
    }


def settings_from_persistable(
    data: dict[str, Any],
    defaults: Optional[Settings] = None,
) -> Settings:
    """Restore Settings from persisted data.

    Args:
        data: Dict loaded from config file.
        defaults: Default Settings to use for missing values.

    Returns:
        Settings object with values from data, falling back to defaults.
    """
    if defaults is None:
        defaults = Settings()

    def get_int(key: str, default: int) -> int:
        val = data.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_float(key: str, default: float) -> float:
        val = data.get(key)
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_bool(key: str, default: bool) -> bool:
        val = data.get(key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in {"true", "1", "yes", "on"}

    return Settings(
        resolution=(
            get_int("resolution_width", defaults.resolution[0]),
            get_int("resolution_height", defaults.resolution[1]),
        ),
        frame_rate=get_int("frame_rate", defaults.frame_rate),
        preview_scale=get_float("preview_scale", defaults.preview_scale),
        preview_divisor=get_int("preview_divisor", defaults.preview_divisor),
        audio_enabled=get_bool("audio_enabled", defaults.audio_enabled),
        sample_rate=get_int("sample_rate", defaults.sample_rate),
        # Preserve runtime-only values from defaults
        audio_device_index=defaults.audio_device_index,
        audio_channels=defaults.audio_channels,
    )
