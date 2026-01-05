"""CSI/Picam camera settings window: resolution/FPS and live controls."""

from __future__ import annotations

from typing import Dict, List

from rpi_logger.modules.base.camera_settings_window import (
    CameraSettingsWindowBase,
    BASE_DEFAULT_SETTINGS,
)

try:
    from rpi_logger.modules.CSICameras.app.widgets.sensor_info_dialog import show_sensor_info

    HAS_SENSOR_DIALOG = True
except ImportError:
    HAS_SENSOR_DIALOG = False
    show_sensor_info = None  # type: ignore

# CSI camera default settings (no audio support)
DEFAULT_SETTINGS = BASE_DEFAULT_SETTINGS

# CSI/Picam image controls
IMAGE_CONTROLS = [
    "Brightness",
    "Contrast",
    "Saturation",
    "Sharpness",
    "ColourGains",
]

# CSI/Picam exposure/focus controls
EXPOSURE_FOCUS_CONTROLS = [
    "AeExposureMode",
    "ExposureTime",
    "AnalogueGain",
    "AfMode",
    "LensPosition",
    "AwbMode",
    "AeMeteringMode",
    "NoiseReductionMode",
]

# Combined list for backwards compatibility
ESSENTIAL_CONTROLS = IMAGE_CONTROLS + EXPOSURE_FOCUS_CONTROLS

# CSI/Picam control dependencies: child -> (parent, enable_condition)
CONTROL_DEPENDENCIES = {
    "AnalogueGain": ("AeExposureMode", lambda v: v in ("Custom", "Off")),
    "ExposureTime": ("AeExposureMode", lambda v: v in ("Custom", "Off")),
    "LensPosition": ("AfMode", lambda v: v == "Manual"),
}


class CameraSettingsWindow(CameraSettingsWindowBase):
    """CSI/Picam camera settings window."""

    IMAGE_CONTROLS = IMAGE_CONTROLS
    EXPOSURE_FOCUS_CONTROLS = EXPOSURE_FOCUS_CONTROLS
    CONTROL_DEPENDENCIES = CONTROL_DEPENDENCIES
    WINDOW_TITLE_PREFIX = "CSI Camera Settings"
    SUPPORTS_AUDIO = False
    DEFAULT_SETTINGS = DEFAULT_SETTINGS
    BACKEND_DISPLAY_MAP = {"picam": "Pi Camera"}

    @staticmethod
    def _get_sensor_info_dialog():
        """Return CSI module's sensor info dialog."""
        return show_sensor_info, HAS_SENSOR_DIALOG


# Backwards compatibility alias
SettingsWindow = CameraSettingsWindow
