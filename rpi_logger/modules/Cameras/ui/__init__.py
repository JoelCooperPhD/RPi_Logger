"""UI module - view for stub (codex) integration."""

from .view import CameraView, USBCameraView

__all__ = [
    "CameraView",
    "USBCameraView",  # Backwards compatibility alias
]
