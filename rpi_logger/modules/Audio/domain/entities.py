"""Core data structures for the audio domain layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from .level_meter import LevelMeter


@dataclass(slots=True, frozen=True)
class AudioDeviceInfo:
    device_id: int
    name: str
    channels: int
    sample_rate: float


@dataclass(slots=True, frozen=True)
class AudioSnapshot:
    devices: Dict[int, AudioDeviceInfo]
    selected_devices: Dict[int, AudioDeviceInfo]
    level_meters: Dict[int, LevelMeter]
    recording: bool
    trial_number: int
    session_dir: Optional[Path]
    status_text: str


__all__ = ["AudioDeviceInfo", "AudioSnapshot"]
