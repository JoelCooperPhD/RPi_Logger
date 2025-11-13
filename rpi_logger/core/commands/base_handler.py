
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
            if command == "start_session":
                await self.handle_start_session(command_data)
                return True
            elif command == "stop_session":
                await self.handle_stop_session(command_data)
                return True
            elif command in ("record", "start_recording"):
                await self.handle_record(command_data)
                return True
            elif command in ("pause", "stop_recording"):
                await self.handle_pause(command_data)
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

    async def handle_start_session(self, command_data: Dict[str, Any]) -> None:
        self._update_session_dir(command_data)
        self.logger.debug("start_session command received")

    async def handle_stop_session(self, command_data: Dict[str, Any]) -> None:
        self.logger.debug("stop_session command received (no default implementation)")

    async def handle_record(self, command_data: Dict[str, Any]) -> None:
        if not self._check_recording_state(should_be_recording=False):
            return

        try:
            self._update_session_dir(command_data)
            trial_number = command_data.get("trial_number", 1)
            trial_label = command_data.get("trial_label", "")

            if hasattr(self.system, 'trial_label'):
                self.system.trial_label = trial_label

            success = await self._start_recording_impl(command_data, trial_number)

            if success:
                status_data = self._get_recording_started_status_data(trial_number)
                StatusMessage.send("recording_started", status_data)
                self.logger.info("Recording started (trial %d)", trial_number)
                self._sync_gui_recording_state()
            else:
                StatusMessage.send("error", {"message": "Failed to start recording"})
                self.logger.error("Failed to start recording")

        except Exception as e:
            self.logger.exception("Failed to start recording: %s", e)
            StatusMessage.send("error", {
                "message": f"Failed to start recording: {str(e)[:100]}"
            })

    async def handle_pause(self, command_data: Dict[str, Any]) -> None:
        if not self._check_recording_state(should_be_recording=True):
            return

        try:
            success = await self._stop_recording_impl(command_data)

            if success:
                status_data = self._get_recording_stopped_status_data()
                StatusMessage.send("recording_stopped", status_data)
                self.logger.info("Recording paused")
                self._sync_gui_recording_state()
            else:
                StatusMessage.send("error", {"message": "Failed to pause recording"})
                self.logger.error("Failed to pause recording")

        except Exception as e:
            self.logger.exception("Failed to pause recording: %s", e)
            StatusMessage.send("error", {
                "message": f"Failed to pause recording: {str(e)[:100]}"
            })

    @abstractmethod
    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def _start_recording_impl(self, command_data: Dict[str, Any], trial_number: int) -> bool:
        pass

    @abstractmethod
    async def _stop_recording_impl(self, command_data: Dict[str, Any]) -> bool:
        pass

    def _update_session_dir(self, command_data: Dict[str, Any]) -> None:
        if "session_dir" not in command_data:
            return

        from pathlib import Path
        session_dir = Path(command_data["session_dir"])

        if hasattr(self.system, 'session_dir'):
            self.system.session_dir = session_dir
        if hasattr(self.system, 'session_label'):
            self.system.session_label = session_dir.name
        if hasattr(self.system, 'output_dir'):
            self.system.output_dir = session_dir

        self.logger.info("Updated session directory to: %s", session_dir)

    def _get_recording_started_status_data(self, trial_number: int) -> Dict[str, Any]:
        return {"trial": trial_number}

    def _get_recording_stopped_status_data(self) -> Dict[str, Any]:
        return {}

    def _sync_gui_recording_state(self) -> None:
        if self.gui and hasattr(self.gui, 'sync_recording_state'):
            self.gui.sync_recording_state()

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
            from rpi_logger.modules.base import gui_utils

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
                from rpi_logger.modules.base import sanitize_error_message
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

        # CRITICAL: Destroy window to exit main_loop()
        # main_loop() only exits on TclError from destroyed window
        if self.gui:
            window = None
            if hasattr(self.gui, 'root'):
                window = self.gui.root
            elif hasattr(self.gui, 'window'):
                window = self.gui.window

            if window:
                try:
                    window.destroy()
                    self.logger.info("QUIT_HANDLER: ✓ Destroyed window")
                except Exception as e:
                    self.logger.error("QUIT_HANDLER: ✗ Failed to destroy window: %s", e)

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
        Standardized handler for recording record/pause actions.

        This method encapsulates the common pattern:
        1. Check recording state
        2. Execute the action callback
        3. Send success/error status message

        Args:
            action: 'record' or 'pause' (used for status messages)
            callback: The function/method to call for the action
            extra_data: Optional additional data to include in success status
            is_async: True if callback is async, False if sync

        Example usage in subclass:
            async def handle_record(self, command_data):
                await self._handle_recording_action(
                    'record',
                    lambda: self.system.record(),
                    extra_data={'cameras': len(self.system.cameras)}
                )
        """
        # Determine expected state based on action
        should_be_recording = (action == 'pause')

        if not self._check_recording_state(should_be_recording):
            return

        try:
            # Execute the callback
            if is_async:
                result = await callback()
            else:
                result = callback()

            # Send success status
            status_name = f"recording_{'started' if action == 'record' else 'stopped'}"
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
