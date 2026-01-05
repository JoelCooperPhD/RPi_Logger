"""USB camera settings window: resolution/FPS and live controls."""

from __future__ import annotations

from typing import Any, Dict, List

from rpi_logger.modules.base.camera_settings_window import (
    CameraSettingsWindowBase,
    BASE_DEFAULT_SETTINGS,
)

try:
    from rpi_logger.modules.Cameras.app.widgets.sensor_info_dialog import show_sensor_info

    HAS_SENSOR_DIALOG = True
except ImportError:
    HAS_SENSOR_DIALOG = False
    show_sensor_info = None  # type: ignore

# USB camera default settings (includes audio)
DEFAULT_SETTINGS = {
    **BASE_DEFAULT_SETTINGS,
    "record_audio": "true",
}

# USB camera image controls
IMAGE_CONTROLS = ["Brightness", "Contrast", "Saturation", "Hue"]

# USB camera exposure/focus controls
EXPOSURE_FOCUS_CONTROLS = [
    "AutoExposure", "AeExposureMode", "Exposure", "ExposureTime", "Gain", "AnalogueGain",
    "AutoFocus", "FocusAutomaticContinuous", "AfMode", "Focus", "FocusAbsolute",
    "AwbMode", "WhiteBalanceBlueU", "WhiteBalanceRedV",
]

ESSENTIAL_CONTROLS = IMAGE_CONTROLS + EXPOSURE_FOCUS_CONTROLS

# USB camera control dependencies: child -> (parent, enable_condition)
CONTROL_DEPENDENCIES = {
    "Gain": ("AutoExposure", lambda v: str(v).startswith("1:") or v is True),
    "Exposure": ("AutoExposure", lambda v: str(v).startswith("1:") or v is True),
    "FocusAbsolute": ("FocusAutomaticContinuous", lambda v: not v),
    "AnalogueGain": ("AeExposureMode", lambda v: v in ("Custom", "Off")),
    "ExposureTime": ("AeExposureMode", lambda v: v in ("Custom", "Off")),
}


class CameraSettingsWindow(CameraSettingsWindowBase):
    """USB camera settings window with audio support and v4l2 enum parsing."""

    IMAGE_CONTROLS = IMAGE_CONTROLS
    EXPOSURE_FOCUS_CONTROLS = EXPOSURE_FOCUS_CONTROLS
    CONTROL_DEPENDENCIES = CONTROL_DEPENDENCIES
    WINDOW_TITLE_PREFIX = "Camera Settings"
    SUPPORTS_AUDIO = True
    DEFAULT_SETTINGS = DEFAULT_SETTINGS
    BACKEND_DISPLAY_MAP = {"usb": "USB", "picam": "Pi Camera"}

    @staticmethod
    def _get_sensor_info_dialog():
        """Return USB module's sensor info dialog."""
        return show_sensor_info, HAS_SENSOR_DIALOG

    def _parse_enum_value(self, raw_value: str) -> Any:
        """Parse v4l2 enum value format: 'value:label' -> int value."""
        if ":" in str(raw_value):
            return int(raw_value.split(":")[0])
        return raw_value


# Backwards compatibility alias
SettingsWindow = CameraSettingsWindow
