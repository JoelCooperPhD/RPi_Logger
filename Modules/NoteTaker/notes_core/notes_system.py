
import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from Modules.base import BaseSystem, RecordingStateMixin
from . import NotesInitializationError
from .notes_handler import NotesHandler

logger = logging.getLogger(__name__)


class NotesSystem(BaseSystem, RecordingStateMixin):

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.notes_handler: Optional[NotesHandler] = None


    async def _initialize_devices(self) -> None:
        try:
            logger.info("Initializing NoteTaker module...")

            module_session_dir = self.session_dir / "NoteTaker"
            self.notes_handler = NotesHandler(module_session_dir)

            self.initialized = True
            logger.info("NoteTaker module initialized successfully")

        except Exception as e:
            error_msg = f"Failed to initialize NoteTaker: {e}"
            logger.error(error_msg, exc_info=True)
            raise NotesInitializationError(error_msg) from e

    def _create_mode_instance(self, mode_name: str) -> Any:
        if mode_name == "gui":
            from .modes.gui_mode import GUIMode
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        elif mode_name == "headless":
            logger.error("Headless mode not implemented for NoteTaker")
            raise ValueError(f"Unsupported mode: {mode_name}")
        else:
            raise ValueError(f"Unknown mode: {mode_name}")

    async def start_recording(self) -> bool:
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            logger.warning("Cannot start recording: %s", error_msg)
            return False

        if not self.notes_handler:
            logger.error("Cannot start recording - notes handler not initialized")
            return False

        try:
            if self.notes_handler.start_recording():
                self.recording = True
                logger.info("Note recording started")
                return True
            else:
                logger.error("Failed to start note recording")
                return False

        except Exception as e:
            logger.error("Exception starting recording: %s", e, exc_info=True)
            return False

    async def stop_recording(self) -> bool:
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            logger.warning("Cannot stop recording: %s", error_msg)
            return False

        try:
            if self.notes_handler.stop_recording():
                self.recording = False
                logger.info("Note recording stopped")
                return True
            else:
                logger.error("Failed to stop note recording")
                return False

        except Exception as e:
            logger.error("Exception stopping recording: %s", e, exc_info=True)
            return False

    def add_note(self, note_text: str) -> bool:
        if not self.initialized or not self.notes_handler:
            logger.error("Cannot add note - system not initialized")
            return False

        if not self.recording:
            logger.warning("Cannot add note - recording not active")
            return False

        result = self.notes_handler.add_note(note_text)
        return result is not None

    async def cleanup(self) -> None:
        logger.info("Cleaning up NoteTaker system...")

        try:
            if self.recording and self.notes_handler:
                await self.stop_recording()

            self.running = False
            self.initialized = False

            logger.info("NoteTaker cleanup completed")

        except Exception as e:
            logger.error("Error during cleanup: %s", e, exc_info=True)
