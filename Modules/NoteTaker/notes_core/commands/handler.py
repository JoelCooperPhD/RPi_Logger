
import logging
from typing import TYPE_CHECKING, Optional

from logger_core.commands import BaseCommandHandler, StatusMessage

if TYPE_CHECKING:
    from ..notes_system import NotesSystem

logger = logging.getLogger(__name__)


class CommandHandler(BaseCommandHandler):

    def __init__(self, system: 'NotesSystem', gui: Optional[any] = None):
        super().__init__(system)
        self.gui = gui

    async def _start_recording_impl(self, command_data: dict, trial_number: int) -> bool:
        return await self.system.start_recording()

    async def _stop_recording_impl(self, command_data: dict) -> bool:
        return await self.system.stop_recording()

    def _update_session_dir(self, command_data: dict) -> None:
        super()._update_session_dir(command_data)

        if "session_dir" in command_data:
            from pathlib import Path
            from ..notes_handler import NotesHandler
            session_dir = Path(command_data["session_dir"])
            self.system.notes_handler = NotesHandler(session_dir)

    def _get_recording_started_status_data(self, trial_number: int) -> dict:
        return {"note_count": 0}

    def _get_recording_stopped_status_data(self) -> dict:
        note_count = self.system.notes_handler.note_count if self.system.notes_handler else 0
        return {"note_count": note_count}

    async def handle_get_status(self, command_data: dict) -> None:
        logger.debug("Received get_status command")

        note_count = self.system.notes_handler.note_count if self.system.notes_handler else 0
        elapsed_time = self.system.notes_handler.get_session_elapsed_time() if self.system.notes_handler else "00:00:00"

        StatusMessage.send("status_report", {
            "recording": self.system.recording,
            "initialized": self.system.initialized,
            "note_count": note_count,
            "session_elapsed_time": elapsed_time
        })
