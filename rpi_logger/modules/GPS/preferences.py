"""GPS module preferences helper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rpi_logger.modules.base.preferences import ScopedPreferences


@dataclass(slots=True)
class GPSPreferences:
    """Helper for GPS-specific preferences.

    Wraps ScopedPreferences to provide typed access to GPS settings.
    """

    prefs: Optional[ScopedPreferences]

    def get_bool(self, key: str, default: bool = True) -> bool:
        """Get a boolean preference value."""
        if not self.prefs:
            return default
        raw = self.prefs.get(key)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"true", "1", "yes", "on"}

    def set_bool(self, key: str, value: bool) -> None:
        """Set a boolean preference value."""
        if self.prefs:
            self.prefs.write_sync({key: value})

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a float preference value."""
        if not self.prefs:
            return default
        raw = self.prefs.get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except (ValueError, TypeError):
            return default

    def set_float(self, key: str, value: float) -> None:
        """Set a float preference value."""
        if self.prefs:
            self.prefs.write_sync({key: value})

    def get_str(self, key: str, default: str = "") -> str:
        """Get a string preference value."""
        if not self.prefs:
            return default
        raw = self.prefs.get(key)
        if raw is None:
            return default
        return str(raw)

    def set_str(self, key: str, value: str) -> None:
        """Set a string preference value."""
        if self.prefs:
            self.prefs.write_sync({key: value})

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer preference value."""
        if not self.prefs:
            return default
        raw = self.prefs.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default

    def set_int(self, key: str, value: int) -> None:
        """Set an integer preference value."""
        if self.prefs:
            self.prefs.write_sync({key: value})
