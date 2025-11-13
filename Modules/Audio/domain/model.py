"""Backward compatible shim for the legacy module path."""

from .entities import AudioDeviceInfo, AudioSnapshot
from .state import AudioDevice, AudioModel, AudioState

__all__ = [
    "AudioDevice",
    "AudioDeviceInfo",
    "AudioSnapshot",
    "AudioState",
    "AudioModel",
]
