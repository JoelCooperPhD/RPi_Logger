"""Typed configuration for the DRT module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rpi_logger.modules.base.preferences import ScopedPreferences
from rpi_logger.modules.base.typed_config import (
    get_pref_bool,
    get_pref_int,
    get_pref_str,
    get_pref_path,
)


@dataclass(slots=True)
class DRTConfig:
    """Typed configuration for the DRT (Detection Response Task) module."""

    # Module metadata
    display_name: str = "DRT"
    enabled: bool = False

    # Output settings
    output_dir: Path = field(default_factory=lambda: Path("drt_data"))
    session_prefix: str = "drt"
    log_level: str = "info"
    console_output: bool = False

    # Mode settings
    default_mode: str = "gui"

    # Device settings
    device_vid: int = 0x239A
    device_pid: int = 0x801E
    baudrate: int = 9600

    # Window settings
    window_x: int = 0
    window_y: int = 0
    window_width: int = 800
    window_height: int = 600
    window_geometry: str = ""

    # Recording settings
    auto_start_recording: bool = False

    # UI visibility
    gui_show_session_output: bool = True

    @classmethod
    def from_preferences(
        cls, prefs: ScopedPreferences, args: Any = None
    ) -> "DRTConfig":
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
            # Mode settings
            default_mode=get_pref_str(prefs, "default_mode", defaults.default_mode),
            # Device settings
            device_vid=get_pref_int(prefs, "device_vid", defaults.device_vid),
            device_pid=get_pref_int(prefs, "device_pid", defaults.device_pid),
            baudrate=get_pref_int(prefs, "baudrate", defaults.baudrate),
            # Window settings
            window_x=get_pref_int(prefs, "window_x", defaults.window_x),
            window_y=get_pref_int(prefs, "window_y", defaults.window_y),
            window_width=get_pref_int(prefs, "window_width", defaults.window_width),
            window_height=get_pref_int(prefs, "window_height", defaults.window_height),
            window_geometry=get_pref_str(prefs, "window_geometry", defaults.window_geometry),
            # Recording settings
            auto_start_recording=get_pref_bool(prefs, "auto_start_recording", defaults.auto_start_recording),
            # UI visibility
            gui_show_session_output=get_pref_bool(prefs, "gui_show_session_output", defaults.gui_show_session_output),
        )

        # Apply CLI argument overrides if provided
        if args is not None:
            config = config._apply_args_override(args)

        return config

    def _apply_args_override(self, args: Any) -> "DRTConfig":
        """Apply CLI argument overrides to config values."""
        values = asdict(self)

        arg_mappings = {
            "output_dir": "output_dir",
            "session_prefix": "session_prefix",
            "log_level": "log_level",
            "console_output": "console_output",
            "mode": "default_mode",
            "device_vid": "device_vid",
            "device_pid": "device_pid",
            "baudrate": "baudrate",
        }

        for arg_name, config_key in arg_mappings.items():
            if hasattr(args, arg_name):
                val = getattr(args, arg_name)
                if val is not None:
                    values[config_key] = val

        return DRTConfig(**values)

    def to_dict(self) -> dict[str, Any]:
        """Export config values as dictionary."""
        return asdict(self)


__all__ = ["DRTConfig"]
