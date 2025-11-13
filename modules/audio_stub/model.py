"""Backward compatible shim for the legacy module path."""

from .state import AudioDevice, AudioDeviceInfo, AudioSnapshot, AudioState, AudioStubModel

__all__ = [
    "AudioDevice",
    "AudioDeviceInfo",
    "AudioSnapshot",
    "AudioState",
    "AudioStubModel",
]
