"""Typed configuration for the VOG module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rpi_logger.modules.base.preferences import ScopedPreferences
from rpi_logger.modules.base.typed_config import (
    get_pref_bool,
    get_pref_str,
    get_pref_path,
)


@dataclass(slots=True)
class VOGConfig:
    """Typed configuration for the VOG (Visual Occlusion Glasses) module."""

    # Module metadata
    display_name: str = "VOG"
    enabled: bool = True

    # Output settings
    output_dir: Path = field(default_factory=lambda: Path("vog_data"))
    session_prefix: str = "vog"
    log_level: str = "info"
    console_output: bool = False

    # UI visibility (master logger integration)
    preview_resolution: str = "auto"
    view_show_io_panel: bool = True
    view_show_logger: bool = False
    gui_io_stub_visible: bool = False
    window_geometry: str = "320x200"
    config_dialog_geometry: str = ""
    device_connected: bool = False

    @classmethod
    def from_preferences(
        cls, prefs: ScopedPreferences, args: Any = None
    ) -> "VOGConfig":
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
            # UI visibility
            preview_resolution=get_pref_str(prefs, "preview_resolution", defaults.preview_resolution),
            view_show_io_panel=get_pref_bool(prefs, "view.show_io_panel", defaults.view_show_io_panel),
            view_show_logger=get_pref_bool(prefs, "view.show_logger", defaults.view_show_logger),
            gui_io_stub_visible=get_pref_bool(prefs, "gui_io_stub_visible", defaults.gui_io_stub_visible),
            window_geometry=get_pref_str(prefs, "window_geometry", defaults.window_geometry),
            config_dialog_geometry=get_pref_str(prefs, "config_dialog_geometry", defaults.config_dialog_geometry),
            device_connected=get_pref_bool(prefs, "device_connected", defaults.device_connected),
        )

        # Apply CLI argument overrides if provided
        if args is not None:
            config = config._apply_args_override(args)

        return config

    def _apply_args_override(self, args: Any) -> "VOGConfig":
        """Apply CLI argument overrides to config values."""
        values = asdict(self)

        arg_mappings = {
            "output_dir": "output_dir",
            "session_prefix": "session_prefix",
            "log_level": "log_level",
            "console_output": "console_output",
        }

        for arg_name, config_key in arg_mappings.items():
            if hasattr(args, arg_name):
                val = getattr(args, arg_name)
                if val is not None:
                    values[config_key] = val

        return VOGConfig(**values)

    def to_dict(self) -> dict[str, Any]:
        """Export config values as dictionary."""
        return asdict(self)


__all__ = ["VOGConfig"]
