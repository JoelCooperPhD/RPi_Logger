
import asyncio
import logging
from typing import Any, TYPE_CHECKING

from rpi_logger.modules.base.modes import BaseGUIMode
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..notes_system import NotesSystem

logger = logging.getLogger(__name__)


class GUIMode(BaseGUIMode):

    def __init__(self, system: 'NotesSystem', enable_commands: bool = False):
        super().__init__(system, enable_commands)

    def create_gui(self) -> Any:
        from ..interfaces.gui.tkinter_gui import TkinterGUI

        gui = TkinterGUI(self.system, self.system.args)
        return gui

    def create_command_handler(self, gui: Any) -> CommandHandler:
        return CommandHandler(self.system, gui=gui)

    def get_preview_update_interval(self) -> float:
        return 0.5

    def update_preview(self) -> None:
        if self.gui and hasattr(self.gui, 'update_elapsed_time'):
            self.gui.update_elapsed_time()

    def sync_recording_state(self) -> None:
        if self.gui:
            self.gui.sync_recording_state()

    async def cleanup(self) -> None:
        logger.info("Cleaning up GUI mode...")

        try:
            if self.system.recording:
                await self.system.stop_recording()

        except Exception as e:
            logger.error("Error during GUI mode cleanup: %s", e, exc_info=True)
