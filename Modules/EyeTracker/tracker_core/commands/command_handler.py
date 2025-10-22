#!/usr/bin/env python3
"""
Command handler for eye tracker system.

Processes JSON commands from master and dispatches to appropriate handlers.
"""

import logging
from typing import TYPE_CHECKING, Dict, Any

from logger_core.commands import BaseCommandHandler, StatusMessage

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem


class CommandHandler(BaseCommandHandler):
    """Handles JSON commands for the eye tracker system."""

    def __init__(self, system: 'TrackerSystem', gui=None):
        """
        Initialize command handler.

        Args:
            system: Reference to TrackerSystem instance
            gui: Optional reference to TkinterGUI instance (for get_geometry)
        """
        super().__init__(system, gui=gui)

    async def handle_start_recording(self, command_data: Dict[str, Any]) -> None:
        """Handle start_recording command."""
        if not self._check_recording_state(should_be_recording=False):
            return

        try:
            # Start recording via recording manager
            if hasattr(self.system, 'recording_manager'):
                self.system.recording_manager.start_recording()
                self.system.recording = True
                self.logger.info("Recording started")
                StatusMessage.send("recording_started", {
                    "experiment_dir": str(self.system.recording_manager.current_experiment_dir)
                })
            else:
                self.logger.error("Recording manager not available")
                StatusMessage.send("error", {
                    "message": "Recording manager not available"
                })

        except Exception as e:
            self.logger.exception("Failed to start recording: %s", e)
            StatusMessage.send("error", {
                "message": f"Failed to start recording: {str(e)[:100]}"
            })

    async def handle_stop_recording(self, command_data: Dict[str, Any]) -> None:
        """Handle stop_recording command."""
        if not self._check_recording_state(should_be_recording=True):
            return

        try:
            # Stop recording via recording manager
            if hasattr(self.system, 'recording_manager'):
                self.system.recording_manager.stop_recording()
                self.system.recording = False
                self.logger.info("Recording stopped")
                StatusMessage.send("recording_stopped", {})
            else:
                self.logger.error("Recording manager not available")
                StatusMessage.send("error", {
                    "message": "Recording manager not available"
                })

        except Exception as e:
            self.logger.exception("Failed to stop recording: %s", e)
            StatusMessage.send("error", {
                "message": f"Failed to stop recording: {str(e)[:100]}"
            })

    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        """Handle get_status command."""
        try:
            status_data = {
                "running": self.system.running,
                "recording": self.system.recording,
                "connected": hasattr(self.system, 'device_manager') and
                           self.system.device_manager.is_connected,
            }

            if hasattr(self.system, 'frame_count'):
                status_data["frame_count"] = self.system.frame_count

            if self.system.recording and hasattr(self.system, 'recording_manager'):
                status_data["experiment_dir"] = str(
                    self.system.recording_manager.current_experiment_dir
                )

            StatusMessage.send("status_report", status_data)

        except Exception as e:
            self.logger.exception("Failed to get status: %s", e)
            StatusMessage.send("error", {
                "message": f"Failed to get status: {str(e)[:100]}"
            })
