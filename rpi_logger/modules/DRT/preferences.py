from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rpi_logger.modules.base.preferences import ScopedPreferences


@dataclass(slots=True)
class DRTPreferences:
    prefs: Optional[ScopedPreferences]

    def get_bool(self, key: str, default: bool = True) -> bool:
        if not self.prefs:
            return default
        raw = self.prefs.get(key)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"true", "1", "yes", "on"}

    def set_bool(self, key: str, value: bool) -> None:
        if self.prefs:
            self.prefs.write_sync({key: value})
