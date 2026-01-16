"""Command routing."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from rpi_logger.core.commands import StatusType

if TYPE_CHECKING:  # pragma: no cover - avoids circular import at runtime
    from .application import AudioApp


class CommandRouter:
    """Route commands/actions to handlers."""
    def __init__(self, logger: logging.Logger, app: "AudioApp") -> None:
        self.logger = logger.getChild("CommandRouter")
        self.app = app

    async def handle_command(self, command: dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action == "start_recording":
            trial_number = int(command.get("trial_number", self.app.pending_trial_number))
            trial_label = command.get("trial_label", "")
            await self.app.start_recording(trial_number, trial_label)
            return True
        if action in ("stop_recording", "pause"):
            await self.app.stop_recording()
            return True
        if action == "get_status":
            self.app._emit_status(StatusType.STATUS_REPORT, self.app.state.status_payload())
            return True
        if action == "start_session":
            await self.app.ensure_session_dir()
            return True
        if action == "stop_session":
            await self.app.stop_recording()
            self.app.state.set_session_dir(None)
            return True
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        action = (action or "").lower()
        if action == "start_recording":
            await self.app.start_recording()
            return True
        if action == "stop_recording":
            await self.app.stop_recording()
            return True
        return False


__all__ = ["CommandRouter"]
