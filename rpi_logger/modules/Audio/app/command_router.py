"""Command + user action routing for the audio module."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from rpi_logger.core.commands import StatusType

if TYPE_CHECKING:  # pragma: no cover - avoids circular import at runtime
    from .application import AudioApp


class CommandRouter:
    """Route commands/user actions to the appropriate handler."""

    def __init__(self, logger: logging.Logger, app: "AudioApp") -> None:
        self.logger = logger.getChild("CommandRouter")
        self.app = app

    async def handle_command(self, command: dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        self.logger.debug("Handling command: %s", action)
        if action == "start_recording":
            trial = int(command.get("trial_number", self.app.pending_trial_number))
            await self.app.start_recording(trial)
            return True
        if action == "stop_recording":
            await self.app.stop_recording()
            return True
        if action == "get_status":
            self.app._emit_status(StatusType.STATUS_REPORT, self.app.state.status_payload())
            return True
        if action == "start_session":
            await self.app.ensure_session_dir()
            return True
        self.logger.debug("Unhandled command: %s", action)
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        action = (action or "").lower()
        self.logger.debug("Handling user action: %s", action)
        if action == "start_recording":
            await self.app.start_recording()
            return True
        if action == "stop_recording":
            await self.app.stop_recording()
            return True
        if action == "toggle_device":
            device_id = kwargs.get("device_id")
            enabled = bool(kwargs.get("enabled", True))
            if isinstance(device_id, int):
                await self.app.toggle_device(device_id, enabled)
                return True
        self.logger.debug("Unhandled user action: %s", action)
        return False


__all__ = ["CommandRouter"]
