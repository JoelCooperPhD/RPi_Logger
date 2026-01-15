"""Cameras module.

Camera module with optional audio recording.
Records all frames from camera - no rate limiting.
Camera is configured for desired FPS via fps_hint.
"""

from .bridge import CamerasRuntime, USBCamerasRuntime, factory

__all__ = [
    "CamerasRuntime",
    "USBCamerasRuntime",  # Backwards compatibility alias
    "factory",
]
