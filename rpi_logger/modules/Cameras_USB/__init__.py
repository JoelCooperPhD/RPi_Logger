"""Cameras_USB module.

USB camera module with optional audio recording.
Architecture: "Capture Fast, Record Slow"
- Captures at hardware speed
- Consumer throttles to user's frame rate
- Video FPS = actual recorded rate for correct playback
"""

from .bridge import USBCamerasRuntime, factory

__all__ = [
    "USBCamerasRuntime",
    "factory",
]
