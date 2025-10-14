#!/usr/bin/env python3
"""
Command handler for audio recording system.

Processes JSON commands and dispatches to appropriate handlers.
"""

import logging
from typing import TYPE_CHECKING, Dict, Any

from .command_protocol import StatusMessage

if TYPE_CHECKING:
    from ..audio_system import AudioSystem

logger = logging.getLogger("CommandHandler")


class CommandHandler:
    """Handles commands for audio recording system in slave mode."""

    def __init__(self, audio_system: 'AudioSystem'):
        """
        Initialize command handler.

        Args:
            audio_system: Audio system instance to control
        """
        self.system = audio_system
        self.logger = logging.getLogger("CommandHandler")

    async def handle_command(self, command_data: Dict[str, Any]) -> None:
        """
        Handle incoming command from master.

        Args:
            command_data: Parsed command dictionary
        """
        command = command_data.get("command", "")
        self.logger.debug("Received command: %s", command)

        try:
            if command == "start_recording":
                await self._handle_start_recording()
            elif command == "stop_recording":
                await self._handle_stop_recording()
            elif command == "get_status":
                await self._handle_get_status()
            elif command == "toggle_device":
                device_id = command_data.get("device_id")
                enabled = command_data.get("enabled", True)
                await self._handle_toggle_device(device_id, enabled)
            elif command == "quit":
                await self._handle_quit()
            else:
                StatusMessage.send("error", {"message": f"Unknown command: {command}"})
                self.logger.warning("Unknown command: %s", command)

        except Exception as e:
            error_msg = f"Command '{command}' failed: {e}"
            StatusMessage.send("error", {"message": error_msg})
            self.logger.error(error_msg)

    async def _handle_start_recording(self) -> None:
        """Handle start_recording command."""
        if self.system.recording:
            StatusMessage.send("error", {"message": "Already recording"})
            return

        success = self.system.start_recording()
        if success:
            device_count = len(self.system.active_handlers)
            StatusMessage.send("recording_started", {
                "devices": device_count,
                "recording_count": self.system.recording_count
            })
            self.logger.info("Recording started on %d devices", device_count)
        else:
            StatusMessage.send("error", {"message": "Failed to start recording"})

    async def _handle_stop_recording(self) -> None:
        """Handle stop_recording command."""
        if not self.system.recording:
            StatusMessage.send("error", {"message": "Not recording"})
            return

        await self.system.stop_recording()
        StatusMessage.send("recording_stopped", {
            "recording_count": self.system.recording_count
        })
        self.logger.info("Recording stopped")

    async def _handle_get_status(self) -> None:
        """Handle get_status command."""
        status_data = {
            "recording": self.system.recording,
            "recording_count": self.system.recording_count,
            "devices_available": len(self.system.available_devices),
            "devices_selected": len(self.system.selected_devices),
            "devices_recording": len(self.system.active_handlers) if self.system.recording else 0,
            "session": self.system.session_label,
        }
        StatusMessage.send("status_report", status_data)
        self.logger.debug("Status report sent")

    async def _handle_toggle_device(self, device_id: int, enabled: bool) -> None:
        """
        Handle toggle_device command.

        Args:
            device_id: Audio device ID to toggle
            enabled: True to enable, False to disable
        """
        if device_id is None:
            StatusMessage.send("error", {"message": "device_id required"})
            return

        if enabled:
            success = self.system.select_device(device_id)
            action = "selected"
        else:
            success = self.system.deselect_device(device_id)
            action = "deselected"

        if success:
            StatusMessage.send("device_toggled", {
                "device_id": device_id,
                "enabled": enabled
            })
            self.logger.info("Device %d %s", device_id, action)
        else:
            StatusMessage.send("error", {"message": f"Failed to toggle device {device_id}"})

    async def _handle_quit(self) -> None:
        """Handle quit command."""
        StatusMessage.send("shutting_down", {})
        self.logger.info("Quit command received")
        self.system.shutdown_event.set()
