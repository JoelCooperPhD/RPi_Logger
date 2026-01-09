"""Cameras_USB module.

USB camera module with optional audio recording using Elm/Redux architecture.
"""

from .bridge import USBCamerasRuntime, factory

__all__ = [
    "USBCamerasRuntime",
    "factory",
]
