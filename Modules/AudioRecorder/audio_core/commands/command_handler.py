#!/usr/bin/env python3
"""
Command handler for audio recording system.

Processes JSON commands and dispatches to appropriate handlers.
"""

import logging
from typing import TYPE_CHECKING, Dict, Any

from logger_core.commands import BaseCommandHandler, StatusMessage

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class CommandHandler(BaseCommandHandler):
    """Handles commands for audio recording system in slave mode."""

    def __init__(self, audio_system: 'AudioSystem', gui=None):
        """
        Initialize command handler.

        Args:
            audio_system: Audio system instance to control
            gui: Optional reference to GUI window (for get_geometry)
        """
        super().__init__(audio_system)
        self.gui = gui

    async def handle_start_recording(self, command_data: Dict[str, Any]) -> None:
        """Handle start_recording command."""
        if not self._check_recording_state(should_be_recording=False):
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

    async def handle_stop_recording(self, command_data: Dict[str, Any]) -> None:
        """Handle stop_recording command."""
        if not self._check_recording_state(should_be_recording=True):
            return

        await self.system.stop_recording()
        StatusMessage.send("recording_stopped", {
            "recording_count": self.system.recording_count
        })
        self.logger.info("Recording stopped")

    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
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

    async def handle_get_geometry(self, command_data: Dict[str, Any]) -> None:
        """Handle get_geometry command - report current window geometry to parent."""
        if self.gui and hasattr(self.gui, 'window') and self.gui.window:
            try:
                # Get current window geometry
                geometry_str = self.gui.window.geometry()  # Returns "WIDTHxHEIGHT+X+Y"
                parts = geometry_str.replace('+', 'x').replace('-', 'x-').split('x')
                if len(parts) >= 4:
                    width = int(parts[0])
                    height = int(parts[1])
                    x = int(parts[2])
                    y = int(parts[3])
                    StatusMessage.send("geometry_changed", {
                        "width": width,
                        "height": height,
                        "x": x,
                        "y": y
                    })
                    self.logger.debug("Sent geometry to parent: %dx%d+%d+%d", width, height, x, y)
                else:
                    StatusMessage.send("error", {"message": "Failed to parse window geometry"})
            except Exception as e:
                StatusMessage.send("error", {"message": f"Failed to get geometry: {str(e)}"})
                self.logger.error("Failed to get geometry: %s", e)
        else:
            # No GUI available - send a warning but don't fail
            self.logger.debug("No GUI available for get_geometry command")

    async def handle_custom_command(self, command: str, command_data: Dict[str, Any]) -> bool:
        """Handle audio-specific custom commands."""
        if command == "toggle_device":
            device_id = command_data.get("device_id")
            enabled = command_data.get("enabled", True)
            return await self._handle_toggle_device(device_id, enabled)

        return False  # Not handled

    async def _handle_toggle_device(self, device_id: int, enabled: bool) -> bool:
        """
        Handle toggle_device command.

        Args:
            device_id: Audio device ID to toggle
            enabled: True to enable, False to disable

        Returns:
            True (command was handled)
        """
        if device_id is None:
            StatusMessage.send("error", {"message": "device_id required"})
            return True

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

        return True
