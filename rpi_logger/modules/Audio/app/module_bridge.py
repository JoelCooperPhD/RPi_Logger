"""State sync bridge."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable


class ModuleBridge:
    """Sync state with shared model."""
    def __init__(self, module_model, logger: logging.Logger, *,
                 on_recording_change: Callable[[bool], None],
                 on_trial_change: Callable[[Any], None],
                 on_session_change: Callable[[Any], None]) -> None:
        self.module_model = module_model
        self.logger = logger.getChild("ModuleBridge")
        self._suppress = {"recording": False, "trial": False, "session": False}
        self._handlers = {
            "recording": on_recording_change,
            "trial_number": on_trial_change,
            "session_dir": on_session_change,
        }
        if hasattr(self.module_model, "subscribe"):
            self.module_model.subscribe(self._handle_bridge_event)

    def _set_suppressed(self, attr: str, suppress_key: str, value: Any) -> None:
        self._suppress[suppress_key] = True
        try:
            setattr(self.module_model, attr, value)
        finally:
            self._suppress[suppress_key] = False

    def set_recording(self, active: bool, trial: int | None = None) -> None:
        self._set_suppressed("recording", "recording", active)
        if trial is not None:
            self.set_trial_number(trial)

    def set_trial_number(self, trial: int) -> None:
        self._set_suppressed("trial_number", "trial", trial)

    def set_session_dir(self, path: Path) -> None:
        self._set_suppressed("session_dir", "session", path)

    def _handle_bridge_event(self, prop: str, value: Any) -> None:
        suppress_key = {"recording": "recording", "trial_number": "trial", "session_dir": "session"}.get(prop)
        if suppress_key and self._suppress.get(suppress_key):
            return
        handler = self._handlers.get(prop)
        if handler:
            handler(value if value or prop != "session_dir" else None)


__all__ = ["ModuleBridge"]
