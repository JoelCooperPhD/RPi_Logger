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

    async def on_async_bridge_started(self) -> None:
        logger.info("Async bridge started, initializing USB device monitor...")
        if not self.system.initialized:
            try:
                await self.system._initialize_devices()
                logger.info("USB device monitor initialized successfully")

                if self.enable_commands:
                    from logger_core.commands import StatusMessage
                    StatusMessage.send("initialized", {"status": "ready"})
                    logger.info("Sent initialized status to parent")
            except Exception as e:
                logger.error("Failed to initialize USB device monitor: %s", e, exc_info=True)

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
        logger.info(f"GUIMode: on_device_connected called for {port}")
        if self.gui and hasattr(self.gui, 'on_device_connected'):
            logger.info(f"GUIMode: GUI instance has on_device_connected method")
            if self.async_bridge:
                logger.info(f"GUIMode: Using async_bridge to call GUI update for {port}")
                self.async_bridge.call_in_gui(self.gui.on_device_connected, port)
                logger.info(f"GUIMode: Scheduled GUI update via async_bridge for {port}")
            else:
                logger.warning(f"GUIMode: No async_bridge available, calling directly for {port}")
                self.gui.on_device_connected(port)
        else:
            logger.warning(f"GUIMode: GUI or on_device_connected method not available")

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
        logger.info("Cleaning up GUI mode...")

        try:
            if self.system.recording:
                await self.system.stop_recording()

        except Exception as e:
            logger.error("Error during GUI mode cleanup: %s", e, exc_info=True)
