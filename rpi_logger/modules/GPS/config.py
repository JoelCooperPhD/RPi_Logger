"""Typed configuration for the GPS module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rpi_logger.modules.base.preferences import ScopedPreferences
from rpi_logger.modules.base.typed_config import (
    get_pref_bool,
    get_pref_float,
    get_pref_int,
    get_pref_path,
    get_pref_str,
)


@dataclass(slots=True)
class GPSConfig:
    """Typed configuration for the GPS module."""

    # Module metadata
    display_name: str = "GPS"
    enabled: bool = True

    # Output settings
    output_dir: Path = field(default_factory=lambda: Path("gps_data"))
    session_prefix: str = "gps"
    log_level: str = "info"
    console_output: bool = False

    # Map settings
    offline_db: str = "offline_tiles.db"
    center_lat: float = 40.7608
    center_lon: float = -111.8910
    zoom: float = 13.0

    # Serial configuration
    serial_port: str = "/dev/serial0"
    baud_rate: int = 9600
    reconnect_delay_s: float = 3.0
    nmea_history: int = 30

    # UI visibility (master logger integration)
    preview_resolution: str = "auto"
    gui_io_stub_visible: bool = False
    gui_logger_visible: bool = False
    view_show_io_panel: bool = False
    view_show_logger: bool = True

    @classmethod
    def from_preferences(
        cls, prefs: ScopedPreferences, args: Any = None
    ) -> "GPSConfig":
        """Build config from preferences with optional CLI overrides."""
        defaults = cls()

        config = cls(
            # Module metadata
            display_name=get_pref_str(prefs, "display_name", defaults.display_name),
            enabled=get_pref_bool(prefs, "enabled", defaults.enabled),
            # Output settings
            output_dir=get_pref_path(prefs, "output_dir", defaults.output_dir),
            session_prefix=get_pref_str(prefs, "session_prefix", defaults.session_prefix),
            log_level=get_pref_str(prefs, "log_level", defaults.log_level),
            console_output=get_pref_bool(prefs, "console_output", defaults.console_output),
            # Map settings
            offline_db=get_pref_str(prefs, "offline_db", defaults.offline_db),
            center_lat=get_pref_float(prefs, "center_lat", defaults.center_lat),
            center_lon=get_pref_float(prefs, "center_lon", defaults.center_lon),
            zoom=get_pref_float(prefs, "zoom", defaults.zoom),
            # Serial configuration
            serial_port=get_pref_str(prefs, "serial_port", defaults.serial_port),
            baud_rate=get_pref_int(prefs, "baud_rate", defaults.baud_rate),
            reconnect_delay_s=get_pref_float(prefs, "reconnect_delay_s", defaults.reconnect_delay_s),
            nmea_history=get_pref_int(prefs, "nmea_history", defaults.nmea_history),
            # UI visibility
            preview_resolution=get_pref_str(prefs, "preview_resolution", defaults.preview_resolution),
            gui_io_stub_visible=get_pref_bool(prefs, "gui_io_stub_visible", defaults.gui_io_stub_visible),
            gui_logger_visible=get_pref_bool(prefs, "gui_logger_visible", defaults.gui_logger_visible),
            view_show_io_panel=get_pref_bool(prefs, "view.show_io_panel", defaults.view_show_io_panel),
            view_show_logger=get_pref_bool(prefs, "view.show_logger", defaults.view_show_logger),
        )

        # Apply CLI argument overrides if provided
        if args is not None:
            config = config._apply_args_override(args)

        return config

    def _apply_args_override(self, args: Any) -> "GPSConfig":
        """Apply CLI argument overrides to config values."""
        values = asdict(self)

        arg_mappings = {
            "output_dir": "output_dir",
            "session_prefix": "session_prefix",
            "log_level": "log_level",
            "console_output": "console_output",
            "offline_db": "offline_db",
            "center_lat": "center_lat",
            "center_lon": "center_lon",
            "zoom": "zoom",
            "nmea_history": "nmea_history",
        }

        for arg_name, config_key in arg_mappings.items():
            if hasattr(args, arg_name):
                val = getattr(args, arg_name)
                if val is not None:
                    values[config_key] = val

        return GPSConfig(**values)

    def to_dict(self) -> dict[str, Any]:
        """Export config values as dictionary."""
        return asdict(self)


__all__ = ["GPSConfig"]
