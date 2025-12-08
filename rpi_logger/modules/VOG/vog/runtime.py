"""VOG module runtime for VMC integration.

This module provides the VMC-compatible runtime that wraps VOGSystem's
core functionality with VMC model binding, view binding, and command dispatch.

Device discovery is centralized in the main logger. This runtime waits for
device assignments via assign_device commands.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from vmc.runtime import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir
from rpi_logger.modules.VOG.vog_core.config.config_loader import load_config_file
from rpi_logger.modules.VOG.vog_core.vog_handler import VOGHandler
from rpi_logger.modules.VOG.vog_core.device_types import VOGDeviceType
from rpi_logger.modules.VOG.vog_core.protocols import SVOGProtocol, WVOGProtocol
from rpi_logger.modules.VOG.vog_core.transports import USBTransport, XBeeProxyTransport, BaseTransport
from rpi_logger.core.commands import StatusMessage


class VOGModuleRuntime(ModuleRuntime):
    """VMC-compatible runtime for VOG module.

    This runtime manages device handlers and provides the bridge between
    the VOG core functionality and the VMC framework (model binding, view binding,
    command dispatch).

    Device discovery is handled by the main logger. This runtime receives
    device assignments via assign_device commands.
    """

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        self.module_dir = context.module_dir
        self.logger = context.logger.getChild("Runtime")
        self.model = context.model
        self.controller = context.controller
        self.view = context.view
        self.display_name = context.display_name

        # Configuration
        self.config_path = Path(getattr(self.args, "config_path", self.module_dir / "config.txt"))
        self.config_file_path = self.config_path
        self.config: Dict[str, Any] = load_config_file(self.config_path)

        self.session_prefix = str(getattr(self.args, "session_prefix", self.config.get("session_prefix", "vog")))
        self.enable_gui_commands = bool(getattr(self.args, "enable_commands", False))

        # Session/output management
        self.output_root: Path = Path(getattr(self.args, "output_dir", Path("vog_data")))
        self.session_dir: Path = self.output_root
        self.module_subdir: str = "VOG"
        self.module_data_dir: Path = self.session_dir

        # Device management - devices are assigned by main logger
        self.handlers: Dict[str, VOGHandler] = {}
        self.device_types: Dict[str, VOGDeviceType] = {}
        self._transports: Dict[str, BaseTransport] = {}

        # XBee proxy transports for wireless devices (separate from USB transports)
        self._proxy_transports: Dict[str, XBeeProxyTransport] = {}

        # Background tasks
        self.task_manager = BackgroundTaskManager(name="VOGRuntimeTasks", logger=self.logger)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # State tracking
        self._suppress_recording_event = False
        self._suppress_session_event = False
        self._recording_active = False
        self._session_active = False  # True when experiment started (exp>1 sent)

        # Trial state (used by handler for logging)
        self.trial_label: str = ""
        self.active_trial_number: int = 1

    # ------------------------------------------------------------------
    # Lifecycle hooks (VMC ModuleRuntime interface)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the runtime - bind to view/model and wait for device assignments."""
        self.logger.info("Starting VOG runtime (waiting for device assignments)")
        self._loop = asyncio.get_running_loop()

        # Bind to view if available
        if self.view:
            self.view.bind_runtime(self)

        # Initialize session directory
        await self._ensure_session_dir(self.model.session_dir)

        # Subscribe to model changes
        self.model.subscribe(self._on_model_change)

        self.logger.info("VOG runtime ready; waiting for device assignments")

        # Notify logger that module is ready for commands
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        """Shutdown the runtime - stop session and disconnect all devices."""
        self.logger.info("Shutting down VOG runtime")
        await self._stop_session()

        # Disconnect all devices
        for device_id in list(self.handlers.keys()):
            await self.unassign_device(device_id)

    async def cleanup(self) -> None:
        """Final cleanup - shutdown background tasks."""
        await self.task_manager.shutdown()
        self.logger.info("VOG runtime cleanup complete")

    # ------------------------------------------------------------------
    # Device Assignment (from main logger)
    # ------------------------------------------------------------------

    async def assign_device(
        self,
        device_id: str,
        device_type: str,
        port: str,
        baudrate: int,
        is_wireless: bool = False,
        command_id: str | None = None,
        display_name: str = "",
    ) -> bool:
        """
        Assign a device to this module (called by main logger).

        Args:
            device_id: Unique device identifier
            device_type: Device type string (e.g., "sVOG", "wVOG_USB", "wVOG_Wireless")
            port: Serial port path
            baudrate: Serial baudrate
            is_wireless: Whether this is a wireless device
            command_id: Correlation ID for acknowledgment tracking
            display_name: Display name for the device (e.g., "USB: VOG Device ACM0")

        Returns:
            True if device was successfully assigned
        """
        if device_id in self.handlers:
            self.logger.warning("Device %s already assigned", device_id)
            return True

        self.logger.info(
            "Assigning device: id=%s, type=%s, port=%s, baudrate=%d, wireless=%s",
            device_id, device_type, port, baudrate, is_wireless
        )

        try:
            # Determine device type for protocol selection
            device_type_lower = device_type.lower()
            if 'wvog' in device_type_lower:
                protocol = WVOGProtocol()
                vog_device_type = VOGDeviceType.WVOG_USB if not is_wireless else VOGDeviceType.WVOG_WIRELESS
            else:
                protocol = SVOGProtocol()
                vog_device_type = VOGDeviceType.SVOG

            if is_wireless:
                # Wireless device - use proxy transport for XBee communication
                transport = XBeeProxyTransport(
                    node_id=device_id,
                    send_callback=self._request_xbee_send
                )
                if not await transport.connect():
                    self.logger.error("Failed to initialize proxy transport for %s", device_id)
                    StatusMessage.send("device_error", {"device_id": device_id, "error": "Failed to initialize proxy transport"}, command_id=command_id)
                    return False
                self._proxy_transports[device_id] = transport
                self._transports[device_id] = transport  # Also store in main dict for handler access
                self.logger.info("Created XBee proxy transport for %s", device_id)
            else:
                # USB device - create transport
                transport = USBTransport(port, baudrate)
                await transport.connect()

                if not transport.is_connected:
                    self.logger.error("Failed to connect to device %s on %s", device_id, port)
                    StatusMessage.send("device_error", {"device_id": device_id, "error": f"Failed to connect on {port}"}, command_id=command_id)
                    return False

                self._transports[device_id] = transport

            # Create handler (same for both USB and wireless)
            handler = VOGHandler(
                transport,
                device_id,  # Use device_id for consistency (works for both port and node_id)
                self.module_data_dir,
                system=self,
                protocol=protocol
            )
            handler.set_data_callback(self._on_device_data)

            await handler.initialize_device()
            await handler.start()

            self.handlers[device_id] = handler
            self.device_types[device_id] = vog_device_type
            self.logger.info("Device %s assigned and started (%s)", device_id, vog_device_type.value)

            # Update window title to show device display name
            if self.view and display_name:
                try:
                    self.view.set_window_title(display_name)
                except Exception:
                    pass  # Ignore if view doesn't support set_window_title

            # Notify view
            if self.view:
                self.view.on_device_connected(device_id, vog_device_type)

            # Send acknowledgement to logger that device is ready
            # Include command_id for correlation tracking
            # This turns the indicator from yellow (CONNECTING) to green (CONNECTED)
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)

            # If session is active, start experiment on new device
            if self._session_active:
                try:
                    await handler.start_experiment()
                    self.logger.info("Started experiment on newly connected device %s", device_id)
                except Exception as exc:
                    self.logger.error("Failed to start experiment on new device %s: %s", device_id, exc)

            # If recording is active, also start trial
            if self._recording_active:
                try:
                    await handler.start_trial()
                    self.logger.info("Started trial on newly connected device %s", device_id)
                except Exception as exc:
                    self.logger.error("Failed to start trial on new device %s: %s", device_id, exc)

            return True

        except Exception as e:
            self.logger.error("Failed to assign device %s: %s", device_id, e, exc_info=True)
            # Clean up on failure
            if device_id in self._transports:
                transport = self._transports.pop(device_id)
                await transport.disconnect()
            if device_id in self._proxy_transports:
                transport = self._proxy_transports.pop(device_id)
                await transport.disconnect()
            StatusMessage.send("device_error", {"device_id": device_id, "error": str(e)}, command_id=command_id)
            return False

    async def unassign_device(self, device_id: str) -> None:
        """
        Unassign a device from this module.

        Args:
            device_id: The device to unassign
        """
        if device_id not in self.handlers:
            self.logger.warning("Device %s not assigned", device_id)
            return

        self.logger.info("Unassigning device: %s", device_id)
        device_type = self.device_types.get(device_id)

        try:
            handler = self.handlers.pop(device_id)
            self.device_types.pop(device_id, None)
            await handler.stop()

            # Clean up transport
            if device_id in self._transports:
                transport = self._transports.pop(device_id)
                await transport.disconnect()
            if device_id in self._proxy_transports:
                self._proxy_transports.pop(device_id)
                # Note: transport already disconnected via _transports

            # Notify view
            if self.view and device_type:
                self.view.on_device_disconnected(device_id, device_type)

            self.logger.info("Device %s unassigned", device_id)

        except Exception as e:
            self.logger.error("Error unassigning device %s: %s", device_id, e, exc_info=True)

    # ------------------------------------------------------------------
    # Command and action handling (VMC ModuleRuntime interface)
    # ------------------------------------------------------------------

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        """Handle VMC commands."""
        action = (command.get("command") or "").lower()

        if action == "assign_device":
            return await self.assign_device(
                device_id=command.get("device_id", ""),
                device_type=command.get("device_type", ""),
                port=command.get("port", ""),
                baudrate=command.get("baudrate", 0),
                is_wireless=command.get("is_wireless", False),
                command_id=command.get("command_id"),  # Pass correlation ID for ack
                display_name=command.get("display_name", ""),
            )

        if action == "unassign_device":
            await self.unassign_device(command.get("device_id", ""))
            return True

        if action == "unassign_all_devices":
            # Disconnect all devices before shutdown to release serial ports
            self.logger.info("Unassigning all devices before shutdown")
            for device_id in list(self.handlers.keys()):
                await self.unassign_device(device_id)
            return True

        if action == "start_recording":
            self.active_trial_number = self._coerce_trial_number(command.get("trial_number"))
            self.trial_label = str(command.get("trial_label", "") or "")
            session_dir = command.get("session_dir")
            if session_dir:
                await self._ensure_session_dir(Path(session_dir), update_model=False)
            return True

        if action == "stop_recording":
            self.trial_label = ""
            return True

        if action == "peek_open":
            await self._peek_open_all()
            return True

        if action == "peek_close":
            await self._peek_close_all()
            return True

        if action == "show_window":
            self._show_window()
            return True

        if action == "hide_window":
            self._hide_window()
            return True

        if action == "xbee_data":
            # Incoming XBee data from main logger - push to proxy transport
            node_id = command.get("node_id", "")
            data = command.get("data", "")
            await self._on_xbee_data(node_id, data)
            return True

        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        """Handle user actions from the GUI."""
        if action == "peek_open":
            await self._peek_open_all()
            return True

        if action == "peek_close":
            await self._peek_close_all()
            return True

        if action == "get_config":
            port = kwargs.get("port")
            await self._get_config(port)
            return True

        return False

    # ------------------------------------------------------------------
    # Model observation
    # ------------------------------------------------------------------

    def _on_model_change(self, prop: str, value: Any) -> None:
        """React to VMC model property changes."""
        if prop == "recording":
            if self._suppress_recording_event:
                return
            if self._loop:
                self._loop.create_task(self._apply_recording_state(bool(value)))

        elif prop == "session_dir":
            if self._suppress_session_event:
                return
            path = Path(value) if value else None
            if self._loop:
                self._loop.create_task(self._ensure_session_dir(path, update_model=False))

    async def _apply_recording_state(self, active: bool) -> None:
        """Apply recording state change from model."""
        if active:
            success = await self._start_recording()
            if not success:
                # Rollback model state
                self._suppress_recording_event = True
                self.model.recording = False
                self._suppress_recording_event = False
        else:
            await self._stop_recording()

    # ------------------------------------------------------------------
    # Device data callback
    # ------------------------------------------------------------------

    async def _on_device_data(self, port: str, data_type: str, payload: Dict[str, Any]) -> None:
        """Handle data received from device - forward to view."""
        self.logger.debug("Device data: port=%s type=%s payload=%s", port, data_type, payload)
        if self.view:
            self.view.on_device_data(port, data_type, payload)

    # ------------------------------------------------------------------
    # Session control (experiment start/stop)
    # ------------------------------------------------------------------

    async def _start_session(self) -> bool:
        """Start experiment session on all devices (sends exp>1)."""
        if self._session_active:
            self.logger.debug("Session already active")
            return True

        if not self.handlers:
            self.logger.warning("Cannot start session - no devices connected")
            return False

        successes = []
        failures = []

        for port, handler in self.handlers.items():
            try:
                started = await handler.start_experiment()
            except Exception as exc:
                self.logger.error("start_experiment failed on %s: %s", port, exc)
                started = False

            if started:
                successes.append((port, handler))
            else:
                failures.append(port)

        if failures:
            self.logger.error("Failed to start session on: %s", ", ".join(failures))
            # Rollback
            for port, handler in successes:
                try:
                    await handler.stop_experiment()
                except Exception as exc:
                    self.logger.warning("Rollback stop_experiment failed on %s: %s", port, exc)
            return False

        self._session_active = True
        self.logger.info("Session started on all devices (exp>1)")
        return True

    async def _stop_session(self) -> None:
        """Stop experiment session on all devices (sends exp>0)."""
        if not self._session_active:
            return

        # First stop any active trial
        if self._recording_active:
            await self._stop_recording()

        failures = []

        for port, handler in self.handlers.items():
            try:
                stopped = await handler.stop_experiment()
            except Exception as exc:
                self.logger.error("stop_experiment failed on %s: %s", port, exc)
                stopped = False

            if not stopped:
                failures.append(port)

        if failures:
            self.logger.error("Failed to stop session on: %s", ", ".join(failures))

        self._session_active = False
        self.logger.info("Session stopped on all devices (exp>0)")

    # ------------------------------------------------------------------
    # Recording control (trial start/stop)
    # ------------------------------------------------------------------

    async def _start_recording(self) -> bool:
        """Start trial/recording on all devices (sends trl>1)."""
        if not self.handlers:
            self.logger.error("Cannot start recording - no devices connected")
            return False

        # Ensure session is started first
        if not self._session_active:
            session_ok = await self._start_session()
            if not session_ok:
                return False

        successes = []
        failures = []

        for port, handler in self.handlers.items():
            try:
                started = await handler.start_trial()
            except Exception as exc:
                self.logger.error("start_trial failed on %s: %s", port, exc)
                started = False

            if started:
                successes.append((port, handler))
            else:
                failures.append(port)

        if failures:
            self.logger.error("Failed to start recording on: %s", ", ".join(failures))
            # Rollback
            for port, handler in successes:
                try:
                    await handler.stop_trial()
                except Exception as exc:
                    self.logger.warning("Rollback stop_trial failed on %s: %s", port, exc)
            return False

        self._recording_active = True
        self.logger.info("Recording started on all devices (trl>1)")

        # Notify view
        if self.view:
            self.view.update_recording_state()

        return True

    async def _stop_recording(self) -> None:
        """Stop trial/recording on all devices (sends trl>0)."""
        if not self._recording_active:
            return

        failures = []

        for port, handler in self.handlers.items():
            try:
                stopped = await handler.stop_trial()
            except Exception as exc:
                self.logger.error("stop_trial failed on %s: %s", port, exc)
                stopped = False

            if not stopped:
                failures.append(port)

        if failures:
            self.logger.error("Failed to stop recording on: %s", ", ".join(failures))

        self._recording_active = False
        self.trial_label = ""
        self.logger.info("Recording stopped on all devices (trl>0)")

        # Notify view
        if self.view:
            self.view.update_recording_state()

    # ------------------------------------------------------------------
    # Peek control
    # ------------------------------------------------------------------

    async def _peek_open_all(self) -> None:
        """Send peek/open command to all devices."""
        for handler in self.handlers.values():
            await handler.peek_open()

    async def _peek_close_all(self) -> None:
        """Send peek/close command to all devices."""
        for handler in self.handlers.values():
            await handler.peek_close()

    # ------------------------------------------------------------------
    # Window visibility control
    # ------------------------------------------------------------------

    def _show_window(self) -> None:
        """Show the VOG window (called when main logger sends show_window command)."""
        if self.view and hasattr(self.view, '_stub_view'):
            stub_view = self.view._stub_view
            if hasattr(stub_view, 'show_window'):
                stub_view.show_window()
                self.logger.info("VOG window shown")

    def _hide_window(self) -> None:
        """Hide the VOG window (called when main logger sends hide_window command)."""
        if self.view and hasattr(self.view, '_stub_view'):
            stub_view = self.view._stub_view
            if hasattr(stub_view, 'hide_window'):
                stub_view.hide_window()
                self.logger.info("VOG window hidden")

    # ------------------------------------------------------------------
    # Config control
    # ------------------------------------------------------------------

    async def _get_config(self, port: Optional[str] = None) -> None:
        """Request config from device(s).

        If port is specified, request config from that device only.
        Otherwise, request from the first connected device.
        """
        if port and port in self.handlers:
            await self.handlers[port].get_device_config()
        elif self.handlers:
            # Default to first connected device
            handler = next(iter(self.handlers.values()))
            await handler.get_device_config()

    # ------------------------------------------------------------------
    # Session directory management
    # ------------------------------------------------------------------

    async def _ensure_session_dir(self, new_dir: Optional[Path], update_model: bool = True) -> None:
        """Ensure session directory exists and update handlers."""
        if new_dir is None:
            self.output_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.session_dir = self.output_root / f"{self.session_prefix}_{timestamp}"
        else:
            self.session_dir = Path(new_dir)

        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.module_data_dir = ensure_module_data_dir(self.session_dir, self.module_subdir)

        # Update all handler output directories
        for handler in self.handlers.values():
            handler.output_dir = self.module_data_dir

        # Sync to model if requested
        if update_model:
            self._suppress_session_event = True
            self.model.session_dir = self.session_dir
            self._suppress_session_event = False

    # ------------------------------------------------------------------
    # Public API for GUI/View
    # ------------------------------------------------------------------

    def get_device_handler(self, device_id: str) -> Optional[VOGHandler]:
        """Get handler for a specific device."""
        return self.handlers.get(device_id)

    def get_device_type(self, device_id: str) -> Optional[VOGDeviceType]:
        """Get device type for a specific device."""
        return self.device_types.get(device_id)

    @property
    def recording(self) -> bool:
        """Whether recording is active."""
        return self._recording_active

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        """Coerce value to int, returning default if not possible."""
        if isinstance(value, int):
            return value
        if value is None:
            return default
        try:
            return int(str(value), 0)
        except (TypeError, ValueError):
            return default

    def _coerce_trial_number(self, value: Any) -> int:
        """Coerce value to a valid trial number (>= 1)."""
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            candidate = getattr(self.model, "trial_number", None)
            try:
                candidate = int(candidate) if candidate is not None else 0
            except (TypeError, ValueError):
                candidate = 0

        if candidate <= 0:
            candidate = 1

        return candidate

    # ------------------------------------------------------------------
    # XBee Wireless Communication
    # ------------------------------------------------------------------

    async def _on_xbee_data(self, node_id: str, data: str) -> None:
        """Handle incoming XBee data from main logger."""
        transport = self._proxy_transports.get(node_id)
        if transport:
            transport.push_data(data)
        else:
            self.logger.debug("Received XBee data for unknown device: %s", node_id)

    async def _request_xbee_send(self, node_id: str, data: str) -> bool:
        """
        Request main logger to send data via XBee.

        This is called by the XBeeProxyTransport when the handler wants
        to send data to the device.
        """
        self.logger.debug("Requesting XBee send to %s: %s", node_id, data[:50] if len(data) > 50 else data)
        StatusMessage.send_xbee_data(node_id, data)
        # Can't know result immediately - it's async through the command protocol
        return True
