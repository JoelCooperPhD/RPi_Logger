"""
Settings Schema Definitions - JSON/Pydantic-style schemas for all module settings.

Provides validation schemas with types, ranges, and defaults for:
- Audio module settings
- Cameras module settings
- GPS module settings
- DRT module settings
- VOG module settings
- EyeTracker module settings
- Notes module settings
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union


class SettingType(str, Enum):
    """Supported setting value types."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    PATH = "path"
    ENUM = "enum"
    RESOLUTION = "resolution"
    COLOR = "color"


@dataclass
class SettingField:
    """Definition of a single setting field with validation metadata."""
    name: str
    type: SettingType
    default: Any
    description: str = ""
    required: bool = False
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    enum_values: Optional[List[str]] = None
    pattern: Optional[str] = None  # Regex pattern for strings
    nested_group: Optional[str] = None  # For hierarchical settings like "preview.resolution"

    def validate(self, value: Any) -> Tuple[bool, Optional[str]]:
        """
        Validate a value against this field's constraints.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if value is None:
            if self.required:
                return False, f"Field '{self.name}' is required"
            return True, None

        # Type validation
        if self.type == SettingType.STRING:
            if not isinstance(value, str):
                return False, f"Field '{self.name}' must be a string"
            if self.enum_values and value not in self.enum_values:
                return False, f"Field '{self.name}' must be one of: {self.enum_values}"

        elif self.type == SettingType.INTEGER:
            if not isinstance(value, int) or isinstance(value, bool):
                return False, f"Field '{self.name}' must be an integer"
            if self.min_value is not None and value < self.min_value:
                return False, f"Field '{self.name}' must be >= {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"Field '{self.name}' must be <= {self.max_value}"

        elif self.type == SettingType.FLOAT:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"Field '{self.name}' must be a number"
            if self.min_value is not None and value < self.min_value:
                return False, f"Field '{self.name}' must be >= {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"Field '{self.name}' must be <= {self.max_value}"

        elif self.type == SettingType.BOOLEAN:
            if not isinstance(value, bool):
                return False, f"Field '{self.name}' must be a boolean"

        elif self.type == SettingType.PATH:
            if not isinstance(value, (str, Path)):
                return False, f"Field '{self.name}' must be a path string"

        elif self.type == SettingType.ENUM:
            if self.enum_values and value not in self.enum_values:
                return False, f"Field '{self.name}' must be one of: {self.enum_values}"

        elif self.type == SettingType.RESOLUTION:
            # Resolution can be "WIDTHxHEIGHT" string or tuple
            if isinstance(value, str):
                parts = value.lower().split("x")
                if len(parts) != 2:
                    return False, f"Field '{self.name}' must be in format 'WIDTHxHEIGHT'"
                try:
                    int(parts[0])
                    int(parts[1])
                except ValueError:
                    return False, f"Field '{self.name}' must have integer width and height"
            elif isinstance(value, (list, tuple)):
                if len(value) != 2:
                    return False, f"Field '{self.name}' must be [width, height]"
            else:
                return False, f"Field '{self.name}' must be a resolution string or tuple"

        elif self.type == SettingType.COLOR:
            # Color can be RGB tuple or list
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                return False, f"Field '{self.name}' must be [R, G, B] color tuple"
            for component in value:
                if not isinstance(component, int) or not 0 <= component <= 255:
                    return False, f"Field '{self.name}' color components must be 0-255"

        return True, None

    def to_dict(self) -> Dict[str, Any]:
        """Export field definition as dictionary for API schema response."""
        result = {
            "name": self.name,
            "type": self.type.value,
            "default": self.default if not isinstance(self.default, Path) else str(self.default),
            "description": self.description,
            "required": self.required,
        }
        if self.min_value is not None:
            result["min"] = self.min_value
        if self.max_value is not None:
            result["max"] = self.max_value
        if self.enum_values:
            result["enum"] = self.enum_values
        if self.pattern:
            result["pattern"] = self.pattern
        if self.nested_group:
            result["group"] = self.nested_group
        return result


@dataclass
class SettingsSchema:
    """Complete schema definition for a module's settings."""
    module_name: str
    display_name: str
    fields: List[SettingField] = field(default_factory=list)
    description: str = ""

    def validate(self, settings: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate a settings dictionary against this schema.

        Returns:
            Tuple of (all_valid, list of error messages)
        """
        errors = []
        for field_def in self.fields:
            # Handle nested keys with dot notation
            value = self._get_nested_value(settings, field_def.name)
            is_valid, error = field_def.validate(value)
            if not is_valid:
                errors.append(error)

        return len(errors) == 0, errors

    def _get_nested_value(self, data: Dict[str, Any], key: str) -> Any:
        """Get value from nested dict using dot notation (e.g., 'preview.resolution')."""
        parts = key.split(".")
        current = data
        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None
        return current

    def get_field(self, name: str) -> Optional[SettingField]:
        """Get a field definition by name."""
        for field_def in self.fields:
            if field_def.name == name:
                return field_def
        return None

    def get_defaults(self) -> Dict[str, Any]:
        """Get all default values as a flat dictionary."""
        return {
            f.name: f.default if not isinstance(f.default, Path) else str(f.default)
            for f in self.fields
        }

    def to_dict(self) -> Dict[str, Any]:
        """Export schema as dictionary for API response."""
        return {
            "module": self.module_name,
            "display_name": self.display_name,
            "description": self.description,
            "fields": [f.to_dict() for f in self.fields],
        }


# =============================================================================
# Audio Settings Schema
# =============================================================================

AUDIO_SETTINGS_SCHEMA = SettingsSchema(
    module_name="audio",
    display_name="Audio",
    description="Audio recording module settings",
    fields=[
        SettingField(
            name="mode",
            type=SettingType.ENUM,
            default="gui",
            description="Interaction mode",
            enum_values=["gui", "headless"],
        ),
        SettingField(
            name="output_dir",
            type=SettingType.PATH,
            default=Path("audio"),
            description="Output directory for audio files",
        ),
        SettingField(
            name="session_prefix",
            type=SettingType.STRING,
            default="audio",
            description="Prefix for session file names",
        ),
        SettingField(
            name="log_level",
            type=SettingType.ENUM,
            default="debug",
            description="Logging level",
            enum_values=["debug", "info", "warning", "error", "critical"],
        ),
        SettingField(
            name="sample_rate",
            type=SettingType.INTEGER,
            default=48000,
            description="Audio sample rate in Hz",
            min_value=8000,
            max_value=96000,
        ),
        SettingField(
            name="console_output",
            type=SettingType.BOOLEAN,
            default=False,
            description="Enable console output logging",
        ),
        SettingField(
            name="meter_refresh_interval",
            type=SettingType.FLOAT,
            default=0.08,
            description="Level meter refresh interval in seconds",
            min_value=0.01,
            max_value=1.0,
        ),
        SettingField(
            name="recorder_start_timeout",
            type=SettingType.FLOAT,
            default=3.0,
            description="Timeout for starting recorder in seconds",
            min_value=0.5,
            max_value=30.0,
        ),
        SettingField(
            name="recorder_stop_timeout",
            type=SettingType.FLOAT,
            default=2.0,
            description="Timeout for stopping recorder in seconds",
            min_value=0.5,
            max_value=30.0,
        ),
        SettingField(
            name="shutdown_timeout",
            type=SettingType.FLOAT,
            default=15.0,
            description="Timeout for module shutdown in seconds",
            min_value=1.0,
            max_value=60.0,
        ),
    ],
)


# =============================================================================
# Cameras Settings Schema
# =============================================================================

CAMERAS_SETTINGS_SCHEMA = SettingsSchema(
    module_name="cameras",
    display_name="Cameras",
    description="Camera capture module settings",
    fields=[
        # Preview settings
        SettingField(
            name="preview.resolution",
            type=SettingType.RESOLUTION,
            default="320x180",
            description="Preview stream resolution",
            nested_group="preview",
        ),
        SettingField(
            name="preview.fps_cap",
            type=SettingType.FLOAT,
            default=10.0,
            description="Preview frames per second cap",
            min_value=1.0,
            max_value=60.0,
            nested_group="preview",
        ),
        SettingField(
            name="preview.format",
            type=SettingType.ENUM,
            default="RGB",
            description="Preview pixel format",
            enum_values=["RGB", "MJPEG", "YUV420", "NV12"],
            nested_group="preview",
        ),
        SettingField(
            name="preview.overlay",
            type=SettingType.BOOLEAN,
            default=True,
            description="Enable preview overlay",
            nested_group="preview",
        ),
        SettingField(
            name="preview.auto_start",
            type=SettingType.BOOLEAN,
            default=False,
            description="Auto-start preview on module load",
            nested_group="preview",
        ),
        # Record settings
        SettingField(
            name="record.resolution",
            type=SettingType.RESOLUTION,
            default="1280x720",
            description="Recording resolution",
            nested_group="record",
        ),
        SettingField(
            name="record.fps_cap",
            type=SettingType.FLOAT,
            default=30.0,
            description="Recording frames per second cap",
            min_value=1.0,
            max_value=120.0,
            nested_group="record",
        ),
        SettingField(
            name="record.format",
            type=SettingType.ENUM,
            default="MJPEG",
            description="Recording pixel format",
            enum_values=["RGB", "MJPEG", "H264", "HEVC"],
            nested_group="record",
        ),
        SettingField(
            name="record.overlay",
            type=SettingType.BOOLEAN,
            default=True,
            description="Enable recording overlay",
            nested_group="record",
        ),
        # Guard settings
        SettingField(
            name="guard.disk_free_gb_min",
            type=SettingType.FLOAT,
            default=1.0,
            description="Minimum free disk space in GB",
            min_value=0.1,
            max_value=100.0,
            nested_group="guard",
        ),
        SettingField(
            name="guard.check_interval_ms",
            type=SettingType.INTEGER,
            default=5000,
            description="Disk check interval in milliseconds",
            min_value=1000,
            max_value=60000,
            nested_group="guard",
        ),
        # Retention settings
        SettingField(
            name="retention.max_sessions",
            type=SettingType.INTEGER,
            default=10,
            description="Maximum number of sessions to retain",
            min_value=1,
            max_value=1000,
            nested_group="retention",
        ),
        SettingField(
            name="retention.prune_on_start",
            type=SettingType.BOOLEAN,
            default=True,
            description="Prune old sessions on module start",
            nested_group="retention",
        ),
        # Storage settings
        SettingField(
            name="storage.base_path",
            type=SettingType.PATH,
            default=Path("./data"),
            description="Base storage path for recordings",
            nested_group="storage",
        ),
        SettingField(
            name="storage.per_camera_subdir",
            type=SettingType.BOOLEAN,
            default=True,
            description="Create subdirectory per camera",
            nested_group="storage",
        ),
        # Telemetry settings
        SettingField(
            name="telemetry.emit_interval_ms",
            type=SettingType.INTEGER,
            default=2000,
            description="Telemetry emit interval in milliseconds",
            min_value=100,
            max_value=60000,
            nested_group="telemetry",
        ),
        SettingField(
            name="telemetry.include_metrics",
            type=SettingType.BOOLEAN,
            default=True,
            description="Include detailed metrics in telemetry",
            nested_group="telemetry",
        ),
        # Logging settings
        SettingField(
            name="logging.level",
            type=SettingType.ENUM,
            default="INFO",
            description="Logging level",
            enum_values=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            nested_group="logging",
        ),
        SettingField(
            name="logging.file",
            type=SettingType.PATH,
            default=Path("./logs/cameras.log"),
            description="Log file path",
            nested_group="logging",
        ),
    ],
)


# =============================================================================
# GPS Settings Schema
# =============================================================================

GPS_SETTINGS_SCHEMA = SettingsSchema(
    module_name="gps",
    display_name="GPS",
    description="GPS tracking module settings",
    fields=[
        SettingField(
            name="output_dir",
            type=SettingType.PATH,
            default=Path("gps_data"),
            description="Output directory for GPS logs",
        ),
        SettingField(
            name="session_prefix",
            type=SettingType.STRING,
            default="gps",
            description="Prefix for session file names",
        ),
        SettingField(
            name="log_level",
            type=SettingType.ENUM,
            default="info",
            description="Logging level",
            enum_values=["debug", "info", "warning", "error", "critical"],
        ),
        SettingField(
            name="offline_db",
            type=SettingType.STRING,
            default="offline_tiles.db",
            description="Offline map tiles database filename",
        ),
        SettingField(
            name="center_lat",
            type=SettingType.FLOAT,
            default=40.7608,
            description="Default map center latitude",
            min_value=-90.0,
            max_value=90.0,
        ),
        SettingField(
            name="center_lon",
            type=SettingType.FLOAT,
            default=-111.8910,
            description="Default map center longitude",
            min_value=-180.0,
            max_value=180.0,
        ),
        SettingField(
            name="zoom",
            type=SettingType.FLOAT,
            default=13.0,
            description="Default map zoom level",
            min_value=1.0,
            max_value=20.0,
        ),
        SettingField(
            name="serial_port",
            type=SettingType.STRING,
            default="/dev/serial0",
            description="GPS serial port device",
        ),
        SettingField(
            name="baud_rate",
            type=SettingType.INTEGER,
            default=9600,
            description="Serial baud rate",
            min_value=300,
            max_value=115200,
        ),
        SettingField(
            name="reconnect_delay_s",
            type=SettingType.FLOAT,
            default=3.0,
            description="Reconnection delay in seconds",
            min_value=0.5,
            max_value=60.0,
        ),
        SettingField(
            name="nmea_history",
            type=SettingType.INTEGER,
            default=30,
            description="NMEA sentence history buffer size",
            min_value=10,
            max_value=1000,
        ),
        SettingField(
            name="view_show_io_panel",
            type=SettingType.BOOLEAN,
            default=False,
            description="Show I/O panel in view",
        ),
        SettingField(
            name="view_show_logger",
            type=SettingType.BOOLEAN,
            default=True,
            description="Show logger panel in view",
        ),
    ],
)


# =============================================================================
# DRT Settings Schema
# =============================================================================

DRT_SETTINGS_SCHEMA = SettingsSchema(
    module_name="drt",
    display_name="DRT",
    description="Detection Response Task module settings",
    fields=[
        SettingField(
            name="output_dir",
            type=SettingType.PATH,
            default=Path("drt_data"),
            description="Output directory for DRT logs",
        ),
        SettingField(
            name="session_prefix",
            type=SettingType.STRING,
            default="drt",
            description="Prefix for session file names",
        ),
        SettingField(
            name="log_level",
            type=SettingType.ENUM,
            default="info",
            description="Logging level",
            enum_values=["debug", "info", "warning", "error", "critical"],
        ),
        SettingField(
            name="device_vid",
            type=SettingType.INTEGER,
            default=0x239A,
            description="USB Vendor ID for DRT device",
            min_value=0,
            max_value=0xFFFF,
        ),
        SettingField(
            name="device_pid",
            type=SettingType.INTEGER,
            default=0x801E,
            description="USB Product ID for DRT device",
            min_value=0,
            max_value=0xFFFF,
        ),
        SettingField(
            name="baudrate",
            type=SettingType.INTEGER,
            default=9600,
            description="Serial baud rate",
            min_value=300,
            max_value=115200,
        ),
        SettingField(
            name="window_geometry",
            type=SettingType.STRING,
            default="",
            description="Window geometry string (WIDTHxHEIGHT+X+Y)",
        ),
        SettingField(
            name="auto_start_recording",
            type=SettingType.BOOLEAN,
            default=False,
            description="Auto-start recording on session start",
        ),
        SettingField(
            name="gui_show_session_output",
            type=SettingType.BOOLEAN,
            default=True,
            description="Show session output panel in GUI",
        ),
    ],
)


# =============================================================================
# VOG Settings Schema
# =============================================================================

VOG_SETTINGS_SCHEMA = SettingsSchema(
    module_name="vog",
    display_name="VOG",
    description="Visual Occlusion Glasses module settings",
    fields=[
        SettingField(
            name="output_dir",
            type=SettingType.PATH,
            default=Path("vog_data"),
            description="Output directory for VOG logs",
        ),
        SettingField(
            name="session_prefix",
            type=SettingType.STRING,
            default="vog",
            description="Prefix for session file names",
        ),
        SettingField(
            name="log_level",
            type=SettingType.ENUM,
            default="info",
            description="Logging level",
            enum_values=["debug", "info", "warning", "error", "critical"],
        ),
        SettingField(
            name="view_show_io_panel",
            type=SettingType.BOOLEAN,
            default=True,
            description="Show I/O panel in view",
        ),
        SettingField(
            name="view_show_logger",
            type=SettingType.BOOLEAN,
            default=False,
            description="Show logger panel in view",
        ),
        SettingField(
            name="window_geometry",
            type=SettingType.STRING,
            default="320x200",
            description="Window geometry string",
        ),
        SettingField(
            name="config_dialog_geometry",
            type=SettingType.STRING,
            default="",
            description="Config dialog geometry string",
        ),
    ],
)


# =============================================================================
# EyeTracker Settings Schema
# =============================================================================

EYETRACKER_SETTINGS_SCHEMA = SettingsSchema(
    module_name="eyetracker",
    display_name="EyeTracker-Neon",
    description="Pupil Labs Neon eye tracker module settings",
    fields=[
        SettingField(
            name="output_dir",
            type=SettingType.PATH,
            default=Path("neon-eyetracker"),
            description="Output directory for eye tracking data",
        ),
        SettingField(
            name="session_prefix",
            type=SettingType.STRING,
            default="neon_eyetracker",
            description="Prefix for session file names",
        ),
        SettingField(
            name="target_fps",
            type=SettingType.FLOAT,
            default=10.0,
            description="Target scene camera FPS",
            min_value=1.0,
            max_value=60.0,
        ),
        SettingField(
            name="eyes_fps",
            type=SettingType.FLOAT,
            default=30.0,
            description="Eye camera FPS",
            min_value=1.0,
            max_value=200.0,
        ),
        SettingField(
            name="resolution_width",
            type=SettingType.INTEGER,
            default=1280,
            description="Recording resolution width",
            min_value=320,
            max_value=4096,
        ),
        SettingField(
            name="resolution_height",
            type=SettingType.INTEGER,
            default=720,
            description="Recording resolution height",
            min_value=240,
            max_value=2160,
        ),
        SettingField(
            name="auto_start_recording",
            type=SettingType.BOOLEAN,
            default=False,
            description="Auto-start recording on session start",
        ),
        SettingField(
            name="preview_preset",
            type=SettingType.INTEGER,
            default=4,
            description="Preview quality preset (1-5)",
            min_value=1,
            max_value=5,
        ),
        SettingField(
            name="preview_width",
            type=SettingType.INTEGER,
            default=640,
            description="Preview width in pixels",
            min_value=160,
            max_value=1920,
        ),
        SettingField(
            name="preview_height",
            type=SettingType.INTEGER,
            default=480,
            description="Preview height in pixels",
            min_value=120,
            max_value=1080,
        ),
        SettingField(
            name="discovery_timeout",
            type=SettingType.FLOAT,
            default=5.0,
            description="Device discovery timeout in seconds",
            min_value=1.0,
            max_value=60.0,
        ),
        SettingField(
            name="discovery_retry",
            type=SettingType.FLOAT,
            default=3.0,
            description="Device discovery retry interval in seconds",
            min_value=1.0,
            max_value=60.0,
        ),
        SettingField(
            name="enable_recording_overlay",
            type=SettingType.BOOLEAN,
            default=True,
            description="Enable overlay in recordings",
        ),
        SettingField(
            name="include_gaze_in_recording",
            type=SettingType.BOOLEAN,
            default=True,
            description="Include gaze indicator in recording",
        ),
        SettingField(
            name="overlay_font_scale",
            type=SettingType.FLOAT,
            default=0.6,
            description="Overlay text font scale",
            min_value=0.1,
            max_value=3.0,
        ),
        SettingField(
            name="gaze_circle_radius",
            type=SettingType.INTEGER,
            default=60,
            description="Gaze indicator circle radius in pixels",
            min_value=5,
            max_value=200,
        ),
        SettingField(
            name="gaze_shape",
            type=SettingType.ENUM,
            default="circle",
            description="Gaze indicator shape",
            enum_values=["circle", "crosshair", "dot", "ring"],
        ),
        # Stream enable flags
        SettingField(
            name="stream_video_enabled",
            type=SettingType.BOOLEAN,
            default=True,
            description="Enable scene video stream",
        ),
        SettingField(
            name="stream_gaze_enabled",
            type=SettingType.BOOLEAN,
            default=True,
            description="Enable gaze data stream",
        ),
        SettingField(
            name="stream_eyes_enabled",
            type=SettingType.BOOLEAN,
            default=True,
            description="Enable eye camera stream",
        ),
        SettingField(
            name="stream_imu_enabled",
            type=SettingType.BOOLEAN,
            default=True,
            description="Enable IMU data stream",
        ),
        SettingField(
            name="stream_events_enabled",
            type=SettingType.BOOLEAN,
            default=True,
            description="Enable events stream",
        ),
        SettingField(
            name="stream_audio_enabled",
            type=SettingType.BOOLEAN,
            default=True,
            description="Enable audio stream",
        ),
    ],
)


# =============================================================================
# Notes Settings Schema
# =============================================================================

NOTES_SETTINGS_SCHEMA = SettingsSchema(
    module_name="notes",
    display_name="Notes",
    description="Session notes module settings",
    fields=[
        SettingField(
            name="output_dir",
            type=SettingType.PATH,
            default=Path("notes"),
            description="Output directory for notes files",
        ),
        SettingField(
            name="session_prefix",
            type=SettingType.STRING,
            default="notes",
            description="Prefix for session file names",
        ),
        SettingField(
            name="auto_start",
            type=SettingType.BOOLEAN,
            default=False,
            description="Auto-start notes module",
        ),
        SettingField(
            name="history_limit",
            type=SettingType.INTEGER,
            default=200,
            description="Maximum notes history entries",
            min_value=10,
            max_value=10000,
        ),
        SettingField(
            name="log_level",
            type=SettingType.ENUM,
            default="info",
            description="Logging level",
            enum_values=["debug", "info", "warning", "error", "critical"],
        ),
    ],
)


# =============================================================================
# Global Settings Schema
# =============================================================================

GLOBAL_SETTINGS_SCHEMA = SettingsSchema(
    module_name="global",
    display_name="Global Settings",
    description="Application-wide settings",
    fields=[
        SettingField(
            name="output_base_dir",
            type=SettingType.PATH,
            default=Path("./data"),
            description="Base output directory for all modules",
        ),
        SettingField(
            name="log_level",
            type=SettingType.ENUM,
            default="info",
            description="Default logging level",
            enum_values=["debug", "info", "warning", "error", "critical"],
        ),
        SettingField(
            name="auto_save_interval_s",
            type=SettingType.FLOAT,
            default=30.0,
            description="Auto-save interval in seconds",
            min_value=5.0,
            max_value=600.0,
        ),
    ],
)


# =============================================================================
# Schema Registry
# =============================================================================

# Map module names to their schemas
SETTINGS_SCHEMAS: Dict[str, SettingsSchema] = {
    "audio": AUDIO_SETTINGS_SCHEMA,
    "cameras": CAMERAS_SETTINGS_SCHEMA,
    "gps": GPS_SETTINGS_SCHEMA,
    "drt": DRT_SETTINGS_SCHEMA,
    "vog": VOG_SETTINGS_SCHEMA,
    "eyetracker": EYETRACKER_SETTINGS_SCHEMA,
    "notes": NOTES_SETTINGS_SCHEMA,
    "global": GLOBAL_SETTINGS_SCHEMA,
}


def get_schema(module_name: str) -> Optional[SettingsSchema]:
    """Get the settings schema for a module."""
    return SETTINGS_SCHEMAS.get(module_name.lower())


def get_all_schemas() -> Dict[str, SettingsSchema]:
    """Get all available settings schemas."""
    return SETTINGS_SCHEMAS.copy()


def validate_settings(module_name: str, settings: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate settings for a module against its schema.

    Args:
        module_name: Name of the module
        settings: Dictionary of settings to validate

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    schema = get_schema(module_name)
    if not schema:
        return False, [f"No schema found for module '{module_name}'"]
    return schema.validate(settings)


def get_defaults(module_name: str) -> Optional[Dict[str, Any]]:
    """Get default settings for a module."""
    schema = get_schema(module_name)
    if not schema:
        return None
    return schema.get_defaults()


__all__ = [
    "SettingType",
    "SettingField",
    "SettingsSchema",
    "AUDIO_SETTINGS_SCHEMA",
    "CAMERAS_SETTINGS_SCHEMA",
    "GPS_SETTINGS_SCHEMA",
    "DRT_SETTINGS_SCHEMA",
    "VOG_SETTINGS_SCHEMA",
    "EYETRACKER_SETTINGS_SCHEMA",
    "NOTES_SETTINGS_SCHEMA",
    "GLOBAL_SETTINGS_SCHEMA",
    "SETTINGS_SCHEMAS",
    "get_schema",
    "get_all_schemas",
    "validate_settings",
    "get_defaults",
]
