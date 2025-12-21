"""Bridge helpers that sync derived state with the shared model."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable


class ModuleBridge:
    """Synchronize derived state with the codex shared model."""

    def __init__(
        self,
        module_model,
        logger: logging.Logger,
        *,
        on_recording_change: Callable[[bool], None],
        on_trial_change: Callable[[Any], None],
        on_session_change: Callable[[Any], None],
    ) -> None:
        self.module_model = module_model
        self.logger = logger.getChild("ModuleBridge")
        self._suppress_recording = False
        self._suppress_trial = False
        self._suppress_session = False
        self._on_recording_change = on_recording_change
        self._on_trial_change = on_trial_change
        self._on_session_change = on_session_change
        if hasattr(self.module_model, "subscribe"):
            self.module_model.subscribe(self._handle_bridge_event)

    def set_recording(self, active: bool, trial: int | None = None) -> None:
        self._suppress_recording = True
        try:
            self.module_model.recording = active
        finally:
            self._suppress_recording = False
        if trial is not None:
            self.set_trial_number(trial)

    def set_trial_number(self, trial: int) -> None:
        self._suppress_trial = True
        try:
            self.module_model.trial_number = trial
        finally:
            self._suppress_trial = False

    def set_session_dir(self, path: Path) -> None:
        self._suppress_session = True
        try:
            self.module_model.session_dir = path
        finally:
            self._suppress_session = False

    def _handle_bridge_event(self, prop: str, value: Any) -> None:
        if prop == "recording":
            if self._suppress_recording:
                return
            self._on_recording_change(bool(value))
        elif prop == "trial_number":
            if self._suppress_trial:
                return
            self._on_trial_change(value)
        elif prop == "session_dir":
            if self._suppress_session:
                return
            if not value:
                self._on_session_change(None)
                return
            self._on_session_change(value)


__all__ = ["ModuleBridge"]
