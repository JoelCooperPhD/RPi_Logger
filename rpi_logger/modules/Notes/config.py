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
class NotesPreferences:
    """Preferences wrapper for Notes module."""

    prefs: Optional[ScopedPreferences]

    def history_limit(self, fallback: int) -> int:
        if not self.prefs:
            return fallback
        try:
            return int(self.prefs.get("history_limit", fallback))
        except (TypeError, ValueError):
            return fallback

    def auto_start(self, fallback: bool) -> bool:
        if not self.prefs:
            return fallback
        stored = self.prefs.get("auto_start")
        return fallback if stored is None else str(stored).strip().lower() in {"true", "1", "yes", "on"}

    def _write(self, data: dict) -> None:
        if self.prefs:
            self.prefs.write_sync(data)

    def set_history_limit(self, value: int) -> None:
        self._write({"history_limit": value})

    def set_auto_start(self, value: bool) -> None:
        self._write({"auto_start": value})

    def set_last_note_path(self, path: str) -> None:
        self._write({"last_archive_path": path})


@dataclass(slots=True)
class NotesConfig:
    """Typed configuration for Notes module."""
    display_name: str = "Notes"
    enabled: bool = True
    internal: bool = True
    visible: bool = True
    output_dir: Path = field(default_factory=lambda: Path("notes"))
    session_prefix: str = "notes"
    log_level: str = "info"
    console_output: bool = False
    history_limit: int = 200
    auto_start: bool = False
    last_archive_path: Optional[str] = None
    gui_io_stub_visible: bool = False
    gui_logger_visible: bool = False
    view_show_io_panel: bool = False
    view_show_logger: bool = False
    device_connected: bool = False
    window_geometry: str = "320x200"

    @classmethod
    def from_preferences(cls, prefs: ScopedPreferences, args: Any = None) -> "NotesConfig":
        """Build config from preferences with optional CLI overrides."""
        d = cls()
        config = cls(
            display_name=get_pref_str(prefs, "display_name", d.display_name),
            enabled=get_pref_bool(prefs, "enabled", d.enabled),
            internal=get_pref_bool(prefs, "internal", d.internal),
            visible=get_pref_bool(prefs, "visible", d.visible),
            output_dir=get_pref_path(prefs, "output_dir", d.output_dir),
            session_prefix=get_pref_str(prefs, "session_prefix", d.session_prefix),
            log_level=get_pref_str(prefs, "log_level", d.log_level),
            console_output=get_pref_bool(prefs, "console_output", d.console_output),
            history_limit=get_pref_int(prefs, "notes.history_limit", d.history_limit),
            auto_start=get_pref_bool(prefs, "notes.auto_start", d.auto_start),
            last_archive_path=get_pref_str(prefs, "notes.last_archive_path", "") or None,
            gui_io_stub_visible=get_pref_bool(prefs, "gui_io_stub_visible", d.gui_io_stub_visible),
            gui_logger_visible=get_pref_bool(prefs, "gui_logger_visible", d.gui_logger_visible),
            view_show_io_panel=get_pref_bool(prefs, "view.show_io_panel", d.view_show_io_panel),
            view_show_logger=get_pref_bool(prefs, "view.show_logger", d.view_show_logger),
            device_connected=get_pref_bool(prefs, "device_connected", d.device_connected),
            window_geometry=get_pref_str(prefs, "window_geometry", d.window_geometry),
        )
        return config._apply_args_override(args) if args else config

    def _apply_args_override(self, args: Any) -> "NotesConfig":
        """Apply CLI argument overrides to config values."""
        values = asdict(self)
        for key in ("output_dir", "session_prefix", "log_level", "console_output", "history_limit", "auto_start"):
            if hasattr(args, key) and (val := getattr(args, key)) is not None:
                values[key] = val
        return NotesConfig(**values)

    def to_dict(self) -> dict[str, Any]:
        """Export config values as dictionary."""
        return asdict(self)


__all__ = ["NotesConfig", "NotesPreferences"]
