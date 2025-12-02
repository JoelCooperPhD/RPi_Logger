"""VOG command handler for master logger integration."""

from typing import TYPE_CHECKING, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.commands import BaseCommandHandler, StatusMessage

if TYPE_CHECKING:
    from ..vog_system import VOGSystem


class VOGCommandHandler(BaseCommandHandler):
    """Handles JSON commands from master logger for VOG module."""

    def __init__(self, system: 'VOGSystem', gui: Optional[any] = None):
        super().__init__(system, gui)
        self.logger = get_module_logger("VOGCommandHandler")

    async def _start_recording_impl(self, command_data: dict, trial_number: int) -> bool:
        """Start recording on all VOG devices."""
        self.system.active_trial_number = trial_number
        return await self.system.start_recording()

    async def _stop_recording_impl(self, command_data: dict) -> bool:
        """Stop recording on all VOG devices."""
        return await self.system.stop_recording()

    def _update_session_dir(self, command_data: dict) -> None:
        """Update session directory for all handlers."""
        super()._update_session_dir(command_data)

        if "session_dir" in command_data:
            from pathlib import Path
            session_dir = Path(command_data["session_dir"])
            self.logger.info("Updating session_dir to: %s", session_dir)
            for port, handler in self.system.device_handlers.items():
                handler.output_dir = session_dir
                self.logger.info("Updated output_dir for device %s to: %s", port, session_dir)

    def _get_recording_started_status_data(self, trial_number: int) -> dict:
        """Get status data for recording started message."""
        return {"device_count": len(self.system.device_handlers)}

    def _get_recording_stopped_status_data(self) -> dict:
        """Get status data for recording stopped message."""
        return {"device_count": len(self.system.device_handlers)}

    def _sync_gui_recording_state(self) -> None:
        """Sync GUI state with recording state."""
        super()._sync_gui_recording_state()

        if self.gui and hasattr(self.gui, 'device_tabs'):
            for tab in self.gui.device_tabs.values():
                if hasattr(tab, 'plotter') and tab.plotter:
                    if self.system.recording:
                        tab.plotter.start_recording()
                    else:
                        tab.plotter.stop_recording()

    async def handle_start_session(self, command_data: dict) -> None:
        """Handle session start command."""
        await super().handle_start_session(command_data)
        self.logger.info("Received start_session command")

        if self.gui and hasattr(self.gui, 'device_tabs'):
            for tab in self.gui.device_tabs.values():
                if hasattr(tab, 'plotter') and tab.plotter:
                    tab.plotter.start_session()

        self.logger.info("Session started - plot cleared and animation started")

    async def handle_stop_session(self, command_data: dict) -> None:
        """Handle session stop command."""
        await super().handle_stop_session(command_data)
        self.logger.info("Received stop_session command")

        if self.gui and hasattr(self.gui, 'device_tabs'):
            for tab in self.gui.device_tabs.values():
                if hasattr(tab, 'plotter') and tab.plotter:
                    tab.plotter.stop()

        self.logger.info("Session stopped - animation frozen")

    async def handle_get_status(self, command_data: dict) -> None:
        """Handle status request command."""
        self.logger.debug("Received get_status command")

        device_count = len(self.system.device_handlers)
        connected_ports = list(self.system.device_handlers.keys())

        StatusMessage.send("status_report", {
            "recording": self.system.recording,
            "initialized": self.system.initialized,
            "device_count": device_count,
            "connected_ports": connected_ports
        })

    async def handle_custom_command(self, command: str, command_data: dict) -> bool:
        """Handle VOG-specific commands."""
        if command == "peek_open":
            await self.system.peek_open_all()
            StatusMessage.send("peek_open", {"success": True})
            return True
        elif command == "peek_close":
            await self.system.peek_close_all()
            StatusMessage.send("peek_close", {"success": True})
            return True

        return False  # Command not handled
