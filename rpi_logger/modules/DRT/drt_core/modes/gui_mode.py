import asyncio
from rpi_logger.core.logging_utils import get_module_logger
from typing import Any, TYPE_CHECKING, Dict

from rpi_logger.modules.base.modes import BaseGUIMode
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..drt_system import DRTSystem

# Removed: logger = logging.getLogger(__name__)


class GUIMode(BaseGUIMode):

    def __init__(self, system: 'DRTSystem', enable_commands: bool = False):
        super().__init__(system, enable_commands)
        self.logger = get_module_logger("GUIMode")

    async def on_async_bridge_started(self) -> None:
        self.logger.info("Async bridge started - device detection will begin after mainloop starts")

    def create_gui(self) -> Any:
        from ..interfaces.gui.tkinter_gui import TkinterGUI

        gui = TkinterGUI(self.system, self.system.args)

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
        self.logger.info("GUIMode: on_device_connected called for %s", port)
        if self.gui and hasattr(self.gui, 'on_device_connected'):
            self.logger.info("GUIMode: GUI instance has on_device_connected method")

            window = self.get_gui_window()
            if window:
                self.logger.info("GUIMode: Scheduling GUI update via window.after() for %s", port)
                window.after(0, lambda: self.gui.on_device_connected(port))
                self.logger.info("GUIMode: Scheduled GUI update for %s", port)
            else:
                self.logger.warning("GUIMode: No window available for %s", port)
        else:
            self.logger.warning("GUIMode: GUI or on_device_connected method not available")

    async def on_device_disconnected(self, port: str):
        if self.gui and hasattr(self.gui, 'on_device_disconnected'):
            if self.async_bridge:
                self.async_bridge.call_in_gui(self.gui.on_device_disconnected, port)
            else:
                self.gui.on_device_disconnected(port)

    async def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        if self.gui and hasattr(self.gui, 'on_device_data'):
            if self.async_bridge:
                self.async_bridge.call_in_gui(self.gui.on_device_data, port, data_type, data)
            else:
                self.gui.on_device_data(port, data_type, data)

    async def cleanup(self) -> None:
        self.logger.info("Cleaning up GUI mode...")

        try:
            if self.system.recording:
                await self.system.stop_recording()

        except Exception as e:
            self.logger.error("Error during GUI mode cleanup: %s", e, exc_info=True)
