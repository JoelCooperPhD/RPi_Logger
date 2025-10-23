
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

    async def handle_start_recording(self, command_data: dict) -> None:
        logger.info("Received start_recording command")

        if await self.system.start_recording():
            StatusMessage.send("recording_started", {
                "note_count": 0
            })
            logger.info("Recording started successfully")

            if self.gui:
                self.gui.sync_recording_state()
        else:
            StatusMessage.send("error", {
                "message": "Failed to start note recording"
            })
            logger.error("Failed to start recording")

    async def handle_stop_recording(self, command_data: dict) -> None:
        logger.info("Received stop_recording command")

        note_count = self.system.notes_handler.note_count if self.system.notes_handler else 0

        if await self.system.stop_recording():
            StatusMessage.send("recording_stopped", {
                "note_count": note_count
            })
            logger.info("Recording stopped successfully (%d notes)", note_count)

            if self.gui:
                self.gui.sync_recording_state()
        else:
            StatusMessage.send("error", {
                "message": "Failed to stop note recording"
            })
            logger.error("Failed to stop recording")

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
