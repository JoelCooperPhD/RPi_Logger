"""Backward compatible shim for the legacy module path."""

from .state import AudioDevice, AudioDeviceInfo, AudioModel, AudioSnapshot, AudioState

__all__ = [
    "AudioDevice",
    "AudioDeviceInfo",
    "AudioSnapshot",
    "AudioState",
    "AudioModel",
]
