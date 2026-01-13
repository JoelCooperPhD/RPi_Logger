"""Cameras_USB module.

USB camera module with optional audio recording.
Records all frames from camera - no rate limiting.
Camera is configured for desired FPS via fps_hint.
"""

from .bridge import USBCamerasRuntime, factory

__all__ = [
    "USBCamerasRuntime",
    "factory",
]
