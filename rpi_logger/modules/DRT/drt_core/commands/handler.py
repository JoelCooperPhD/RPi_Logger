import logging
from typing import TYPE_CHECKING, Optional

from logger_core.commands import BaseCommandHandler, StatusMessage

if TYPE_CHECKING:
    from ..drt_system import DRTSystem

logger = logging.getLogger(__name__)


class CommandHandler(BaseCommandHandler):

    def __init__(self, system: 'DRTSystem', gui: Optional[any] = None):
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
            session_dir = Path(command_data["session_dir"])
            logger.info(f"Updating session_dir to: {session_dir}")
            for port, handler in self.system.device_handlers.items():
                handler.output_dir = session_dir
                logger.info(f"Updated output_dir for device {port} to: {session_dir}")

    def _get_recording_started_status_data(self, trial_number: int) -> dict:
        return {"device_count": len(self.system.device_handlers)}

    def _get_recording_stopped_status_data(self) -> dict:
        return {"device_count": len(self.system.device_handlers)}

    def _sync_gui_recording_state(self) -> None:
        super()._sync_gui_recording_state()

        if self.gui and hasattr(self.gui, 'device_tabs'):
            for tab in self.gui.device_tabs.values():
                if hasattr(tab, 'plotter') and tab.plotter:
                    if self.system.recording:
                        tab.plotter.start_recording()
                    else:
                        tab.plotter.stop_recording()

    async def handle_start_session(self, command_data: dict) -> None:
        await super().handle_start_session(command_data)
        logger.info("Received start_session command")

        if self.gui:
            for tab in self.gui.device_tabs.values():
                if tab.plotter:
                    tab.plotter.start_session()

        logger.info("Session started - plot cleared and animation started")

    async def handle_stop_session(self, command_data: dict) -> None:
        await super().handle_stop_session(command_data)
        logger.info("Received stop_session command")

        if self.gui:
            for tab in self.gui.device_tabs.values():
                if tab.plotter:
                    tab.plotter.stop()

        logger.info("Session stopped - animation frozen")

    async def handle_get_status(self, command_data: dict) -> None:
        logger.debug("Received get_status command")

        device_count = len(self.system.device_handlers)
        connected_ports = list(self.system.device_handlers.keys())

        StatusMessage.send("status_report", {
            "recording": self.system.recording,
            "initialized": self.system.initialized,
            "device_count": device_count,
            "connected_ports": connected_ports
        })
