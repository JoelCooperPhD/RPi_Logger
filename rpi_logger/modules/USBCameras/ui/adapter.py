"""UI adapter reusing the Cameras preview implementation."""

from __future__ import annotations

from rpi_logger.modules.Cameras.ui import CameraViewAdapter as _CameraViewAdapter


class USBCameraViewAdapter(_CameraViewAdapter):
    """Alias that clarifies intent for the USB module."""

    def reset_camera_toggles(self) -> None:
        """Clear dynamically registered camera toggles before rebuilding the menu."""
        self._camera_toggle_vars.clear()
        self._camera_toggle_labels.clear()
        self._camera_toggle_handlers.clear()
        self._rebuild_settings_menu()


__all__ = ["USBCameraViewAdapter"]
