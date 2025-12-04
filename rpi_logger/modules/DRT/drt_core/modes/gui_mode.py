import asyncio
from rpi_logger.core.logging_utils import get_module_logger
from typing import Any, TYPE_CHECKING, Dict

from rpi_logger.modules.base.modes import BaseGUIMode
from ..commands import CommandHandler
from ..device_types import DRTDeviceType

if TYPE_CHECKING:
    from ..drt_system import DRTSystem

# Removed: logger = logging.getLogger(__name__)


class GUIMode(BaseGUIMode):

    def __init__(self, system: 'DRTSystem', enable_commands: bool = False):
        super().__init__(system, enable_commands)
        self.logger = get_module_logger("GUIMode")

    async def on_async_bridge_started(self) -> None:
        self.logger.info("=== ASYNC BRIDGE STARTED ===")
        self.logger.info("GUI exists: %s", self.gui is not None)
        self.logger.info("async_bridge exists: %s", self.async_bridge is not None)
        # Sync XBee dongle tab state in case dongle was connected before GUI was ready
        await self._sync_xbee_dongle_state()

    async def _sync_xbee_dongle_state(self) -> None:
        """Sync the XBee dongle tab state with current connection status."""
        self.logger.info("=== SYNC XBEE DONGLE STATE ===")
        self.logger.info("system.connection_manager: %s", self.system.connection_manager)
        self.logger.info("system.xbee_connected: %s", self.system.xbee_connected)
        self.logger.info("system.xbee_port: %s", self.system.xbee_port)

        if self.system.xbee_connected:
            port = self.system.xbee_port or ""
            self.logger.info("XBee dongle already connected on %s, syncing GUI state", port)
            await self.on_xbee_status_change('connected', port)
        else:
            self.logger.info("XBee dongle NOT connected yet")

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

    async def on_device_connected(self, device_id: str, device_type: DRTDeviceType):
        self.logger.info("GUIMode: on_device_connected called for %s (%s)", device_id, device_type.value)
        if self.gui and hasattr(self.gui, 'on_device_connected'):
            self.logger.info("GUIMode: GUI instance has on_device_connected method")

            window = self.get_gui_window()
            if window:
                self.logger.info("GUIMode: Scheduling GUI update via window.after() for %s", device_id)
                window.after(0, lambda: self.gui.on_device_connected(device_id, device_type))
                self.logger.info("GUIMode: Scheduled GUI update for %s", device_id)
            else:
                self.logger.warning("GUIMode: No window available for %s", device_id)
        else:
            self.logger.warning("GUIMode: GUI or on_device_connected method not available")

    async def on_device_disconnected(self, device_id: str, device_type: DRTDeviceType):
        if self.gui and hasattr(self.gui, 'on_device_disconnected'):
            if self.async_bridge:
                self.async_bridge.call_in_gui(self.gui.on_device_disconnected, device_id, device_type)
            else:
                self.gui.on_device_disconnected(device_id, device_type)

    async def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        if self.gui and hasattr(self.gui, 'on_device_data'):
            if self.async_bridge:
                self.async_bridge.call_in_gui(self.gui.on_device_data, port, data_type, data)
            else:
                self.gui.on_device_data(port, data_type, data)

    async def on_xbee_status_change(self, status: str, detail: str):
        """Handle XBee dongle status changes."""
        self.logger.info("=== GUIMODE ON_XBEE_STATUS_CHANGE ===")
        self.logger.info("Status: %s, Detail: %s", status, detail)
        self.logger.info("self.gui: %s", self.gui)
        self.logger.info("hasattr on_xbee_dongle_status_change: %s", hasattr(self.gui, 'on_xbee_dongle_status_change') if self.gui else 'N/A')
        self.logger.info("self.async_bridge: %s", self.async_bridge)

        if self.gui and hasattr(self.gui, 'on_xbee_dongle_status_change'):
            if self.async_bridge:
                self.logger.info("Calling via async_bridge.call_in_gui")
                self.async_bridge.call_in_gui(self.gui.on_xbee_dongle_status_change, status, detail)
            else:
                self.logger.info("Calling directly (no async_bridge)")
                self.gui.on_xbee_dongle_status_change(status, detail)
        else:
            self.logger.warning("Cannot call on_xbee_dongle_status_change - gui=%s", self.gui)

    async def cleanup(self) -> None:
        self.logger.info("Cleaning up GUI mode...")

        try:
            if self.system.recording:
                await self.system.stop_recording()

        except Exception as e:
            self.logger.error("Error during GUI mode cleanup: %s", e, exc_info=True)
