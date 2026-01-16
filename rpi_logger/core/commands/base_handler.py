import logging

from rpi_logger.core.logging_utils import get_module_logger
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .command_protocol import StatusMessage


class BaseCommandHandler(ABC):

    def __init__(self, system: Any, gui: Optional[Any] = None):
        self.system = system
        self.gui = gui
        self.logger = get_module_logger(f"{self.__class__.__name__}")

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
            # Device assignment commands (centralized device discovery)
            elif command == "assign_device":
                await self.handle_assign_device(command_data)
                return True
            elif command == "unassign_device":
                await self.handle_unassign_device(command_data)
                return True
            elif command == "show_window":
                await self.handle_show_window(command_data)
                return True
            elif command == "hide_window":
                await self.handle_hide_window(command_data)
                return True
            elif command == "set_log_level":
                await self.handle_set_log_level(command_data)
                return True
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

                try:
                    screen_height = int(window.winfo_screenheight())
                except Exception:
                    screen_height = None

                # Clamp to screen bounds (keeps window above taskbar)
                width, height, x, y = gui_utils.clamp_geometry_to_screen(
                    width, height, x, y,
                    screen_height=screen_height,
                )

                StatusMessage.send("geometry_changed", {
                    "width": width,
                    "height": height,
                    "x": x,
                    "y": y
                })
                self.logger.debug(
                    "Sent geometry to parent: %dx%d+%d+%d",
                    width, height, x, y,
                )
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

        # Send geometry to parent before quitting (parent handles persistence)
        if self.gui and hasattr(self.gui, 'send_geometry_to_parent'):
            try:
                self.gui.send_geometry_to_parent()
                self.logger.info("QUIT_HANDLER: Sent geometry to parent")
            except Exception as e:
                self.logger.debug("QUIT_HANDLER: Failed to send geometry to parent: %s", e)

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

    # =========================================================================
    # Log Level Control
    # =========================================================================

    async def handle_set_log_level(self, command_data: Dict[str, Any]) -> None:
        """
        Handle dynamic log level change from master.

        Expected command_data:
            level: str - Log level name (debug, info, warning, error, critical)
            target: str - Which handler to adjust (console, ui, all)
        """
        level_str = command_data.get("level", "info").upper()
        target = command_data.get("target", "all")

        self.logger.debug("set_log_level: level=%s, target=%s", level_str, target)

        # Try to use ModuleLogManager if available (preferred)
        try:
            from rpi_logger.core.module_log_manager import get_module_log_manager

            log_manager = get_module_log_manager()
            if log_manager:
                log_manager.handle_set_log_level(command_data)
                StatusMessage.send("log_level_changed", {
                    "level": level_str.lower(),
                    "target": target,
                })
                return
        except ImportError:
            pass

        # Fallback: directly adjust handler levels on root logger
        level = getattr(logging, level_str, logging.INFO)
        root_logger = logging.getLogger()

        handlers_updated = 0
        for handler in root_logger.handlers:
            # Skip file handlers (should always stay at DEBUG)
            if isinstance(handler, logging.FileHandler):
                continue

            # Adjust console/stream handlers
            if target in ("console", "all") and isinstance(handler, logging.StreamHandler):
                handler.setLevel(level)
                handlers_updated += 1

        self.logger.info(
            "Log level updated: level=%s, target=%s, handlers=%d",
            level_str, target, handlers_updated
        )

        StatusMessage.send("log_level_changed", {
            "level": level_str.lower(),
            "target": target,
        })

    # =========================================================================
    # Device Assignment Commands (for centralized device discovery)
    # =========================================================================

    async def handle_assign_device(self, command_data: Dict[str, Any]) -> None:
        """
        Handle device assignment from main logger.

        Expected command_data:
            device_id: str - Unique device identifier
            device_type: str - Device type (e.g., "sVOG", "wDRT_Wireless")
            port: str - Serial port path
            baudrate: int - Serial baudrate
            session_dir: Optional[str] - Current session directory
            is_wireless: bool - Whether this is a wireless device
            command_id: Optional[str] - Correlation ID for acknowledgment
        """
        device_id = command_data.get("device_id")
        device_type = command_data.get("device_type")
        port = command_data.get("port")
        baudrate = command_data.get("baudrate")
        session_dir = command_data.get("session_dir")
        is_wireless = command_data.get("is_wireless", False)
        command_id = command_data.get("command_id")  # For acknowledgment tracking

        self.logger.info(
            "assign_device: device_id=%s, type=%s, port=%s, baudrate=%s, wireless=%s, cmd_id=%s",
            device_id, device_type, port, baudrate, is_wireless, command_id
        )

        # Update session dir if provided
        if session_dir:
            self._update_session_dir({"session_dir": session_dir})

        # Delegate to system for actual device handling
        if hasattr(self.system, 'assign_device'):
            try:
                success = await self.system.assign_device(
                    device_id=device_id,
                    device_type=device_type,
                    port=port,
                    baudrate=baudrate,
                    is_wireless=is_wireless,
                )
                if success:
                    # Send device_ready with command_id for acknowledgment tracking
                    StatusMessage.send("device_ready", {
                        "device_id": device_id,
                        "device_type": device_type,
                    }, command_id=command_id)
                else:
                    StatusMessage.send("device_error", {
                        "device_id": device_id,
                        "error": "Failed to assign device",
                    }, command_id=command_id)
            except Exception as e:
                self.logger.error("Failed to assign device %s: %s", device_id, e)
                StatusMessage.send("device_error", {
                    "device_id": device_id,
                    "error": str(e),
                }, command_id=command_id)
        else:
            self.logger.warning("System does not implement assign_device")
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": "Module does not support device assignment",
            }, command_id=command_id)

    async def handle_unassign_device(self, command_data: Dict[str, Any]) -> None:
        """Handle device unassignment from main logger."""
        device_id = command_data.get("device_id")

        self.logger.info("unassign_device: device_id=%s", device_id)

        if hasattr(self.system, 'unassign_device'):
            try:
                await self.system.unassign_device(device_id)
                StatusMessage.send("device_unassigned", {"device_id": device_id})
            except Exception as e:
                self.logger.error("Failed to unassign device %s: %s", device_id, e)
                StatusMessage.send("device_error", {
                    "device_id": device_id,
                    "message": str(e),
                })
        else:
            self.logger.warning("System does not implement unassign_device")

    async def handle_show_window(self, command_data: Dict[str, Any]) -> None:
        """Handle show window command from main logger."""
        self.logger.info("show_window command received")

        if self.gui:
            window = None
            if hasattr(self.gui, 'root'):
                window = self.gui.root
            elif hasattr(self.gui, 'window'):
                window = self.gui.window

            if window:
                try:
                    window.deiconify()
                    window.lift()
                    window.focus_force()
                    StatusMessage.send("window_shown", {})
                    self.logger.info("Window shown")
                except Exception as e:
                    self.logger.error("Failed to show window: %s", e)
                    StatusMessage.send("error", {"message": f"Failed to show window: {e}"})
            else:
                self.logger.warning("No window available to show")
        else:
            self.logger.warning("No GUI available for show_window")

    async def handle_hide_window(self, command_data: Dict[str, Any]) -> None:
        """Handle hide window command from main logger."""
        self.logger.info("hide_window command received")

        if self.gui:
            window = None
            if hasattr(self.gui, 'root'):
                window = self.gui.root
            elif hasattr(self.gui, 'window'):
                window = self.gui.window

            if window:
                try:
                    window.withdraw()
                    StatusMessage.send("window_hidden", {})
                    self.logger.info("Window hidden")
                except Exception as e:
                    self.logger.error("Failed to hide window: %s", e)
                    StatusMessage.send("error", {"message": f"Failed to hide window: {e}"})
            else:
                self.logger.warning("No window available to hide")
        else:
            self.logger.warning("No GUI available for hide_window")
