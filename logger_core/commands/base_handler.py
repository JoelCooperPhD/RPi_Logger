#!/usr/bin/env python3
"""
Base Command Handler

Abstract base class for module command handlers.
Provides common command handling patterns and template methods for modules to override.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .command_protocol import StatusMessage


class BaseCommandHandler(ABC):
    """
    Abstract base class for module command handlers.

    Modules should inherit from this class and implement the abstract methods
    to handle module-specific commands.
    """

    def __init__(self, system: Any, gui: Optional[Any] = None):
        """
        Initialize command handler.

        Args:
            system: Reference to module system (CameraSystem, AudioSystem, etc.)
            gui: Optional reference to GUI instance (for get_geometry)
        """
        self.system = system
        self.gui = gui
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

    async def handle_command(self, command_data: Dict[str, Any]) -> bool:
        """
        Handle incoming command from master.

        Dispatches to appropriate handler based on command type.

        Args:
            command_data: Parsed command dictionary with 'command' key

        Returns:
            True to continue running, False to shutdown (quit command)
        """
        command = command_data.get("command", "").lower()
        self.logger.debug("Received command: %s", command)

        try:
            if command == "start_recording":
                await self.handle_start_recording(command_data)
                return True
            elif command == "stop_recording":
                await self.handle_stop_recording(command_data)
                return True
            elif command == "get_status":
                await self.handle_get_status(command_data)
                return True
            elif command == "get_geometry":
                await self.handle_get_geometry(command_data)
                return True
            elif command == "take_snapshot":
                await self.handle_take_snapshot(command_data)
                return True
            elif command == "quit":
                await self.handle_quit(command_data)
                return False  # Signal shutdown
            else:
                # Try module-specific command
                handled = await self.handle_custom_command(command, command_data)
                if not handled:
                    StatusMessage.send("error", {"message": f"Unknown command: {command}"})
                    self.logger.warning("Unknown command: %s", command)
                return True

        except Exception as e:
            error_msg = f"Command '{command}' failed: {e}"
            StatusMessage.send("error", {"message": error_msg})
            self.logger.error(error_msg, exc_info=True)
            return True

    @abstractmethod
    async def handle_start_recording(self, command_data: Dict[str, Any]) -> None:
        """
        Handle start_recording command.

        Module must implement this to start recording.
        Should send 'recording_started' status on success or 'error' on failure.

        Args:
            command_data: Command parameters
        """
        pass

    @abstractmethod
    async def handle_stop_recording(self, command_data: Dict[str, Any]) -> None:
        """
        Handle stop_recording command.

        Module must implement this to stop recording.
        Should send 'recording_stopped' status on success or 'error' on failure.

        Args:
            command_data: Command parameters
        """
        pass

    @abstractmethod
    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        """
        Handle get_status command.

        Module must implement this to report current status.
        Should send 'status_report' with status data.

        Args:
            command_data: Command parameters
        """
        pass

    async def handle_get_geometry(self, command_data: Dict[str, Any]) -> None:
        """
        Handle get_geometry command - report current window geometry to parent.

        Default implementation handles tkinter windows (root or window attributes).
        Modules without GUI can leave this as is (no-op if gui not available).

        Args:
            command_data: Command parameters
        """
        if not self.gui:
            self.logger.debug("get_geometry command received (no GUI available)")
            return

        # Try to find the window object (could be root, window, etc.)
        window = None
        if hasattr(self.gui, 'root'):
            window = self.gui.root
        elif hasattr(self.gui, 'window'):
            window = self.gui.window
        else:
            self.logger.debug("GUI does not have 'root' or 'window' attribute")
            return

        if not window:
            self.logger.debug("GUI window not available")
            return

        try:
            # Get current window geometry (tkinter format: "WIDTHxHEIGHT+X+Y")
            geometry_str = window.geometry()
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
            # Import sanitize_error_message if available, otherwise use str()
            try:
                from Modules.base import sanitize_error_message
                error_msg = sanitize_error_message(str(e))
            except ImportError:
                error_msg = str(e)

            StatusMessage.send("error", {"message": f"Failed to get geometry: {error_msg}"})
            self.logger.error("Failed to get geometry: %s", e)

    async def handle_take_snapshot(self, command_data: Dict[str, Any]) -> None:
        """
        Handle take_snapshot command.

        Default implementation sends error (not all modules support snapshots).
        Override in modules that support snapshots.

        Args:
            command_data: Command parameters
        """
        StatusMessage.send("error", {"message": "Snapshot not supported by this module"})
        self.logger.warning("take_snapshot not implemented")

    async def handle_quit(self, command_data: Dict[str, Any]) -> None:
        """
        Handle quit command.

        Default implementation sets shutdown_event and sends 'quitting' status.
        Override if custom shutdown logic is needed.

        Args:
            command_data: Command parameters
        """
        self.logger.info("Quit command received")
        StatusMessage.send("quitting", {})

        # Set shutdown event if system has one
        if hasattr(self.system, 'shutdown_event'):
            self.system.shutdown_event.set()

        # Set running flag to False
        if hasattr(self.system, 'running'):
            self.system.running = False

    async def handle_custom_command(self, command: str, command_data: Dict[str, Any]) -> bool:
        """
        Handle module-specific custom commands.

        Override this to add module-specific commands (e.g., toggle_preview, toggle_device).

        Args:
            command: Command name
            command_data: Full command data dict

        Returns:
            True if command was handled, False if unknown
        """
        return False  # Not handled

    def _check_recording_state(self, should_be_recording: bool) -> bool:
        """
        Helper to check if system is in expected recording state.

        Args:
            should_be_recording: Expected recording state

        Returns:
            True if state matches, False otherwise (and sends error status)
        """
        is_recording = getattr(self.system, 'recording', False)

        if should_be_recording and not is_recording:
            StatusMessage.send("error", {"message": "Not currently recording"})
            return False
        elif not should_be_recording and is_recording:
            StatusMessage.send("error", {"message": "Already recording"})
            return False

        return True
