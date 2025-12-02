"""VOG GUI mode."""

import asyncio
from typing import Any, TYPE_CHECKING, Dict

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base.modes import BaseGUIMode

from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..vog_system import VOGSystem


class GUIMode(BaseGUIMode):
    """GUI mode for VOG module."""

    def __init__(self, system: 'VOGSystem', enable_commands: bool = False):
        super().__init__(system, enable_commands)
        self.logger = get_module_logger("VOGGUIMode")

    async def on_async_bridge_started(self) -> None:
        """Called when async bridge is ready."""
        self.logger.info("Async bridge started - device detection will begin after mainloop starts")

    def create_gui(self) -> Any:
        """Create the GUI instance."""
        from ..interfaces.gui.tkinter_gui import VOGTkinterGUI

        gui = VOGTkinterGUI(self.system, self.system.args)
        return gui

    def create_command_handler(self, gui: Any) -> CommandHandler:
        """Create command handler with GUI reference."""
        return CommandHandler(self.system, gui=gui)

    def get_preview_update_interval(self) -> float:
        """Return preview update interval in seconds."""
        return 0.1

    def update_preview(self) -> None:
        """Update GUI preview/display."""
        if self.gui and hasattr(self.gui, 'update_display'):
            self.gui.update_display()

    def sync_recording_state(self) -> None:
        """Sync GUI recording state with system."""
        if self.gui:
            self.gui.sync_recording_state()

    async def on_device_connected(self, port: str):
        """Handle device connection in GUI context."""
        self.logger.info("GUIMode: on_device_connected called for %s", port)
        if self.gui and hasattr(self.gui, 'on_device_connected'):
            window = self.get_gui_window()
            if window:
                window.after(0, lambda: self.gui.on_device_connected(port))
            else:
                self.logger.warning("GUIMode: No window available for %s", port)

    async def on_device_disconnected(self, port: str):
        """Handle device disconnection in GUI context."""
        if self.gui and hasattr(self.gui, 'on_device_disconnected'):
            if self.async_bridge:
                self.async_bridge.call_in_gui(self.gui.on_device_disconnected, port)
            else:
                self.gui.on_device_disconnected(port)

    async def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        """Handle device data in GUI context."""
        if self.gui and hasattr(self.gui, 'on_device_data'):
            if self.async_bridge:
                self.async_bridge.call_in_gui(self.gui.on_device_data, port, data_type, data)
            else:
                self.gui.on_device_data(port, data_type, data)

    async def cleanup(self) -> None:
        """Clean up GUI mode resources."""
        self.logger.info("Cleaning up GUI mode...")

        try:
            if self.system.recording:
                await self.system.stop_recording()
        except Exception as e:
            self.logger.error("Error during GUI mode cleanup: %s", e, exc_info=True)
