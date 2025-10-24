import asyncio
import logging
from typing import Any, TYPE_CHECKING, Dict

from Modules.base.modes import BaseGUIMode
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..drt_system import DRTSystem

logger = logging.getLogger(__name__)


class GUIMode(BaseGUIMode):

    def __init__(self, system: 'DRTSystem', enable_commands: bool = False):
        super().__init__(system, enable_commands)

    def create_gui(self) -> Any:
        from ..interfaces.gui.tkinter_gui import TkinterGUI

        gui = TkinterGUI(self.system, self.system.args)
        gui.set_close_handler(self.on_closing)
        return gui

    def create_command_handler(self, gui: Any) -> CommandHandler:
        return CommandHandler(self.system, gui=gui)

    def get_preview_update_interval(self) -> float:
        return 0.1

    def update_preview(self) -> None:
        if self.gui and hasattr(self.gui, 'update_display'):
            self.gui.update_display()

    def sync_recording_state(self) -> None:
        if self.gui:
            self.gui.sync_recording_state()

    async def on_device_connected(self, port: str):
        if self.gui and hasattr(self.gui, 'on_device_connected'):
            self.gui.on_device_connected(port)

    async def on_device_disconnected(self, port: str):
        if self.gui and hasattr(self.gui, 'on_device_disconnected'):
            self.gui.on_device_disconnected(port)

    async def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        if self.gui and hasattr(self.gui, 'on_device_data'):
            self.gui.on_device_data(port, data_type, data)

    async def cleanup(self) -> None:
        logger.info("Cleaning up GUI mode...")

        try:
            if self.system.recording:
                await self.system.stop_recording()

        except Exception as e:
            logger.error("Error during GUI mode cleanup: %s", e, exc_info=True)
