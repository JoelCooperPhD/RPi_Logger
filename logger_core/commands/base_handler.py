
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .command_protocol import StatusMessage


class BaseCommandHandler(ABC):

    def __init__(self, system: Any, gui: Optional[Any] = None):
        self.system = system
        self.gui = gui
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

    async def handle_command(self, command_data: Dict[str, Any]) -> bool:
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
        pass

    @abstractmethod
    async def handle_stop_recording(self, command_data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        pass

    async def handle_get_geometry(self, command_data: Dict[str, Any]) -> None:
        if not self.gui:
            self.logger.debug("get_geometry command received (no GUI available)")
            return

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
            from Modules.base import gui_utils

            geometry_str = window.geometry()
            parsed = gui_utils.parse_geometry_string(geometry_str)

            if parsed:
                width, height, x, y = parsed

                StatusMessage.send("geometry_changed", {
                    "width": width,
                    "height": height,
                    "x": x,
                    "y": y
                })
                self.logger.debug("Sent geometry to parent: %dx%d+%d+%d", width, height, x, y)
            else:
                StatusMessage.send("error", {"message": f"Failed to parse window geometry: {geometry_str}"})

        except Exception as e:
            try:
                from Modules.base import sanitize_error_message
                error_msg = sanitize_error_message(str(e))
            except ImportError:
                error_msg = str(e)

            StatusMessage.send("error", {"message": f"Failed to get geometry: {error_msg}"})
            self.logger.error("Failed to get geometry: %s", e)

    async def handle_take_snapshot(self, command_data: Dict[str, Any]) -> None:
        StatusMessage.send("error", {"message": "Snapshot not supported by this module"})
        self.logger.warning("take_snapshot not implemented")

    async def handle_quit(self, command_data: Dict[str, Any]) -> None:
        self.logger.info("Quit command received")

        # Save geometry before quitting (for both standalone and parent modes)
        if self.gui:
            self.logger.info("QUIT_HANDLER: Saving geometry before quitting...")

            if hasattr(self.gui, 'save_window_geometry_to_config'):
                try:
                    self.gui.save_window_geometry_to_config()
                    self.logger.info("QUIT_HANDLER: ✓ Saved geometry to local config")
                except Exception as e:
                    self.logger.error("QUIT_HANDLER: ✗ Failed to save to local config: %s", e)

            if hasattr(self.gui, 'send_geometry_to_parent'):
                try:
                    self.gui.send_geometry_to_parent()
                    self.logger.info("QUIT_HANDLER: ✓ Sent geometry to parent")
                except Exception as e:
                    self.logger.error("QUIT_HANDLER: ✗ Failed to send to parent: %s", e)
        else:
            self.logger.debug("QUIT_HANDLER: No GUI available, skipping geometry save")

        StatusMessage.send("quitting", {})

        if hasattr(self.system, 'shutdown_event'):
            self.system.shutdown_event.set()

        if hasattr(self.system, 'running'):
            self.system.running = False

    async def handle_custom_command(self, command: str, command_data: Dict[str, Any]) -> bool:
        return False  # Not handled

    def _check_recording_state(self, should_be_recording: bool) -> bool:
        """
        Check if the system is in the expected recording state.

        Args:
            should_be_recording: True if system should be recording, False otherwise

        Returns:
            True if state matches expectation, False otherwise (and sends error status)
        """
        is_recording = getattr(self.system, 'recording', False)

        if should_be_recording and not is_recording:
            StatusMessage.send("error", {"message": "Not currently recording"})
            return False
        elif not should_be_recording and is_recording:
            StatusMessage.send("error", {"message": "Already recording"})
            return False

        return True

    async def _handle_recording_action(
        self,
        action: str,
        callback: Any,
        extra_data: Optional[Dict[str, Any]] = None,
        is_async: bool = True
    ) -> None:
        """
        Standardized handler for recording start/stop actions.

        This method encapsulates the common pattern:
        1. Check recording state
        2. Execute the action callback
        3. Send success/error status message

        Args:
            action: 'start' or 'stop' (used for status messages)
            callback: The function/method to call for the action
            extra_data: Optional additional data to include in success status
            is_async: True if callback is async, False if sync

        Example usage in subclass:
            async def handle_start_recording(self, command_data):
                await self._handle_recording_action(
                    'start',
                    lambda: self.system.start_recording(),
                    extra_data={'cameras': len(self.system.cameras)}
                )
        """
        # Determine expected state based on action
        should_be_recording = (action == 'stop')

        if not self._check_recording_state(should_be_recording):
            return

        try:
            # Execute the callback
            if is_async:
                result = await callback()
            else:
                result = callback()

            # Send success status
            status_name = f"recording_{action}ed"
            data = extra_data.copy() if extra_data else {}

            # Include result in data if it's a dict
            if isinstance(result, dict):
                data.update(result)

            StatusMessage.send(status_name, data)
            self.logger.info("Recording %s successfully", action)

        except Exception as e:
            error_msg = f"Failed to {action} recording: {str(e)}"
            StatusMessage.send("error", {"message": error_msg})
            self.logger.error(error_msg, exc_info=True)
