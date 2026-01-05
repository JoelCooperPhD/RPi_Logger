from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rpi_logger.modules.base.preferences import ScopedPreferences


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
