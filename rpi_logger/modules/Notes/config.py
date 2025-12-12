"""Typed configuration for the Notes module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from rpi_logger.modules.base.preferences import ScopedPreferences
from rpi_logger.modules.base.typed_config import (
    get_pref_bool,
    get_pref_int,
    get_pref_path,
    get_pref_str,
)


@dataclass(slots=True)
class NotesConfig:
    """Typed configuration for the Notes module."""

    # Module metadata
    display_name: str = "Notes"
    enabled: bool = True
    internal: bool = True
    visible: bool = True

    # Output settings
    output_dir: Path = field(default_factory=lambda: Path("notes"))
    session_prefix: str = "notes"
    log_level: str = "info"
    console_output: bool = False

    # Mode settings
    mode: str = "gui"

    # Notes-specific settings
    history_limit: int = 200
    auto_start: bool = False
    last_archive_path: Optional[str] = None

    # UI visibility (master logger integration)
    gui_io_stub_visible: bool = False
    gui_logger_visible: bool = False
    view_show_io_panel: bool = False
    view_show_logger: bool = False
    device_connected: bool = False
    window_geometry: str = "320x200"

    @classmethod
    def from_preferences(
        cls, prefs: ScopedPreferences, args: Any = None
    ) -> "NotesConfig":
        """Build config from preferences with optional CLI overrides."""
        defaults = cls()

        config = cls(
            # Module metadata
            display_name=get_pref_str(prefs, "display_name", defaults.display_name),
            enabled=get_pref_bool(prefs, "enabled", defaults.enabled),
            internal=get_pref_bool(prefs, "internal", defaults.internal),
            visible=get_pref_bool(prefs, "visible", defaults.visible),
            # Output settings
            output_dir=get_pref_path(prefs, "output_dir", defaults.output_dir),
            session_prefix=get_pref_str(prefs, "session_prefix", defaults.session_prefix),
            log_level=get_pref_str(prefs, "log_level", defaults.log_level),
            console_output=get_pref_bool(prefs, "console_output", defaults.console_output),
            # Mode settings
            mode=get_pref_str(prefs, "mode", defaults.mode),
            # Notes-specific - use notes.* prefix for scoped keys
            history_limit=get_pref_int(prefs, "notes.history_limit", defaults.history_limit),
            auto_start=get_pref_bool(prefs, "notes.auto_start", defaults.auto_start),
            last_archive_path=get_pref_str(prefs, "notes.last_archive_path", "") or None,
            # UI visibility
            gui_io_stub_visible=get_pref_bool(prefs, "gui_io_stub_visible", defaults.gui_io_stub_visible),
            gui_logger_visible=get_pref_bool(prefs, "gui_logger_visible", defaults.gui_logger_visible),
            view_show_io_panel=get_pref_bool(prefs, "view.show_io_panel", defaults.view_show_io_panel),
            view_show_logger=get_pref_bool(prefs, "view.show_logger", defaults.view_show_logger),
            device_connected=get_pref_bool(prefs, "device_connected", defaults.device_connected),
            window_geometry=get_pref_str(prefs, "window_geometry", defaults.window_geometry),
        )

        # Apply CLI argument overrides if provided
        if args is not None:
            config = config._apply_args_override(args)

        return config

    def _apply_args_override(self, args: Any) -> "NotesConfig":
        """Apply CLI argument overrides to config values."""
        values = asdict(self)

        arg_mappings = {
            "output_dir": "output_dir",
            "session_prefix": "session_prefix",
            "log_level": "log_level",
            "console_output": "console_output",
            "mode": "mode",
            "history_limit": "history_limit",
            "auto_start": "auto_start",
        }

        for arg_name, config_key in arg_mappings.items():
            if hasattr(args, arg_name):
                val = getattr(args, arg_name)
                if val is not None:
                    values[config_key] = val

        return NotesConfig(**values)

    def to_dict(self) -> dict[str, Any]:
        """Export config values as dictionary."""
        return asdict(self)


__all__ = ["NotesConfig"]
