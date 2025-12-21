"""Core data structures for the audio domain layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .level_meter import LevelMeter


@dataclass(slots=True, frozen=True)
class AudioDeviceInfo:
    device_id: int
    name: str
    channels: int
    sample_rate: float


@dataclass(slots=True, frozen=True)
class AudioSnapshot:
    device: AudioDeviceInfo | None
    level_meter: LevelMeter | None
    recording: bool
    trial_number: int
    session_dir: Path | None
    status_text: str


__all__ = ["AudioDeviceInfo", "AudioSnapshot"]
