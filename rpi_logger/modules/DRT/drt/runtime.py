"""Runtime that hosts the legacy DRT hardware stack inside the stub framework.

Device discovery is centralized in the main logger. This runtime waits for
device assignments via assign_device commands.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from vmc.runtime import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir
from rpi_logger.modules.DRT.drt_core.config import load_config_file
from rpi_logger.modules.DRT.drt_core.device_types import DRTDeviceType
from rpi_logger.modules.DRT.drt_core.handlers import (
    BaseDRTHandler,
    SDRTHandler,
    WDRTUSBHandler,
    WDRTWirelessHandler,
)
from rpi_logger.modules.DRT.drt_core.transports import USBTransport, XBeeProxyTransport
from rpi_logger.core.commands import StatusMessage


class DRTModuleRuntime(ModuleRuntime):
    """VMC-compatible runtime for DRT module.

    This runtime manages device handlers and provides the bridge between
    the DRT core functionality and the VMC framework (model binding, view binding,
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
        scope_fn = getattr(self.model, "preferences_scope", None)
        pref_scope = scope_fn("drt") if callable(scope_fn) else None
        from rpi_logger.modules.DRT.preferences import DRTPreferences
        self.preferences = DRTPreferences(pref_scope)
        self.config_path = Path(getattr(self.args, "config_path", self.module_dir / "config.txt"))
        self.config_file_path = self.config_path
        self.config: Dict[str, Any] = load_config_file(self.config_path)

        self.session_prefix = str(getattr(self.args, "session_prefix", self.config.get("session_prefix", "drt")))
        self.enable_gui_commands = bool(getattr(self.args, "enable_commands", False))

        self.output_root: Path = Path(getattr(self.args, "output_dir", Path("drt_data")))
        self.session_dir: Path = self.output_root
        self.module_subdir: str = "DRT"
        self.module_data_dir: Path = self.session_dir

        # Device management - devices are assigned by main logger
        self.handlers: Dict[str, BaseDRTHandler] = {}
        self.device_types: Dict[str, DRTDeviceType] = {}
        self._transports: Dict[str, USBTransport] = {}
        self._proxy_transports: Dict[str, XBeeProxyTransport] = {}

        # Background tasks
        self.task_manager = BackgroundTaskManager(name="DRTRuntimeTasks", logger=self.logger)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._suppress_recording_event = False
        self._suppress_session_event = False
        self._recording_active = False
        self.trial_label: str = ""
        self.active_trial_number: int = 1

    # ------------------------------------------------------------------
    # Lifecycle hooks (VMC ModuleRuntime interface)

    async def start(self) -> None:
        """Start the runtime - bind to view/model and wait for device assignments."""
        self.logger.info("Starting DRT runtime (waiting for device assignments)")
        self._loop = asyncio.get_running_loop()

        if self.view:
            self.view.bind_runtime(self)

        await self._ensure_session_dir(self.model.session_dir)

        self.model.subscribe(self._on_model_change)

        self.logger.info("DRT runtime ready; waiting for device assignments")

    async def shutdown(self) -> None:
        """Shutdown the runtime - stop recording and disconnect all devices."""
        self.logger.info("Shutting down DRT runtime")
        await self._stop_recording()

        # Disconnect all devices
        for device_id in list(self.handlers.keys()):
            await self.unassign_device(device_id)

    async def cleanup(self) -> None:
        await self.task_manager.shutdown()
        self.logger.info("DRT runtime cleanup complete")

    # ------------------------------------------------------------------
    # Command and action handling (VMC ModuleRuntime interface)

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
            )

        if action == "unassign_device":
            await self.unassign_device(command.get("device_id", ""))
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

        if action == "show_window":
            self._show_window()
            return True

        if action == "hide_window":
            self._hide_window()
            return True

        if action == "xbee_data":
            # Forward XBee data to the appropriate proxy transport
            node_id = command.get("node_id", "")
            data = command.get("data", "")
            await self._on_xbee_data(node_id, data)
            return True

        if action == "xbee_send_result":
            # Acknowledgment of XBee send - currently just logged
            node_id = command.get("node_id", "")
            success = command.get("success", False)
            self.logger.debug("XBee send result for %s: %s", node_id, success)
            return True

        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        # Recording actions are routed through the controller/model, so nothing to do here.
        return False

    # ------------------------------------------------------------------
    # Model observation

    def _on_model_change(self, prop: str, value: Any) -> None:
        if prop == "recording":
            if self._suppress_recording_event:
                return
            if self._loop:
                self._loop.create_task(self._apply_recording_state(bool(value)))
        elif prop == "session_dir":
            if self._suppress_session_event:
                return
            if value:
                path = Path(value)
            else:
                path = None
            if self._loop:
                self._loop.create_task(self._ensure_session_dir(path, update_model=False))

    async def _apply_recording_state(self, active: bool) -> None:
        if active:
            success = await self._start_recording()
            if not success:
                self._suppress_recording_event = True
                self.model.recording = False
                self._suppress_recording_event = False
        else:
            await self._stop_recording()

    # ------------------------------------------------------------------
    # Device Assignment (from main logger)

    async def assign_device(
        self,
        device_id: str,
        device_type: str,
        port: str,
        baudrate: int,
        is_wireless: bool = False,
    ) -> bool:
        """
        Assign a device to this module (called by main logger).

        Args:
            device_id: Unique device identifier
            device_type: Device type string (e.g., "sDRT", "wDRT_USB", "wDRT_Wireless")
            port: Serial port path
            baudrate: Serial baudrate
            is_wireless: Whether this is a wireless device

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
            # Parse device type string to enum
            drt_device_type = self._parse_device_type(device_type, is_wireless)

            if is_wireless:
                # Wireless device - create proxy transport for XBee communication
                transport = XBeeProxyTransport(
                    node_id=device_id,
                    send_callback=self._request_xbee_send
                )
                if not await transport.connect():
                    self.logger.error("Failed to initialize proxy transport for %s", device_id)
                    return False

                self._proxy_transports[device_id] = transport

                # Create wireless handler
                handler = self._create_handler(drt_device_type, device_id, transport)
                if not handler:
                    await transport.disconnect()
                    self.logger.error("Failed to create wireless handler for %s", device_type)
                    return False
            else:
                # USB device - create transport
                transport = USBTransport(port=port, baudrate=baudrate)
                if not await transport.connect():
                    self.logger.error("Failed to connect to device %s on %s", device_id, port)
                    return False

                self._transports[device_id] = transport

                # Create appropriate handler based on device type
                handler = self._create_handler(drt_device_type, device_id, transport)
                if not handler:
                    await transport.disconnect()
                    self.logger.error("Failed to create handler for %s", device_type)
                    return False

            # Set up data callback
            handler.data_callback = self._on_device_data

            # Start handler
            await handler.start()

            # Store handler and type
            self.handlers[device_id] = handler
            self.device_types[device_id] = drt_device_type

            self.logger.info("Device %s assigned and started (%s)", device_id, drt_device_type.value)

            # Notify view
            if self.view:
                self.view.on_device_connected(device_id, drt_device_type)

            # If recording is active, start experiment on new device
            if self._recording_active:
                handler._trial_label = self.trial_label
                try:
                    await handler.start_experiment()
                    self.logger.info("Started experiment on newly connected device %s", device_id)
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.error("Failed to start experiment on new device %s: %s", device_id, exc)

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

            # Clean up transport (USB or proxy)
            if device_id in self._transports:
                transport = self._transports.pop(device_id)
                await transport.disconnect()
            elif device_id in self._proxy_transports:
                transport = self._proxy_transports.pop(device_id)
                await transport.disconnect()
            elif handler.transport:
                # Fallback: disconnect via handler's transport reference
                await handler.transport.disconnect()

            # Notify view
            if self.view and device_type:
                self.view.on_device_disconnected(device_id, device_type)

            self.logger.info("Device %s unassigned", device_id)

        except Exception as e:
            self.logger.error("Error unassigning device %s: %s", device_id, e, exc_info=True)

    def _parse_device_type(self, device_type: str, is_wireless: bool = False) -> DRTDeviceType:
        """Parse device type string to DRTDeviceType enum."""
        device_type_lower = device_type.lower()

        if 'sdrt' in device_type_lower:
            return DRTDeviceType.SDRT
        elif 'wdrt' in device_type_lower:
            if is_wireless or 'wireless' in device_type_lower:
                return DRTDeviceType.WDRT_WIRELESS
            else:
                return DRTDeviceType.WDRT_USB
        else:
            # Default to sDRT for unknown types
            self.logger.warning("Unknown device type '%s', defaulting to sDRT", device_type)
            return DRTDeviceType.SDRT

    def _create_handler(
        self,
        device_type: DRTDeviceType,
        device_id: str,
        transport: USBTransport,
    ) -> Optional[BaseDRTHandler]:
        """Create the appropriate handler for a device type."""
        if device_type == DRTDeviceType.SDRT:
            return SDRTHandler(
                device_id=device_id,
                output_dir=self.module_data_dir,
                transport=transport
            )
        elif device_type == DRTDeviceType.WDRT_USB:
            return WDRTUSBHandler(
                device_id=device_id,
                output_dir=self.module_data_dir,
                transport=transport
            )
        elif device_type == DRTDeviceType.WDRT_WIRELESS:
            return WDRTWirelessHandler(
                device_id=device_id,
                output_dir=self.module_data_dir,
                transport=transport
            )
        else:
            self.logger.warning("Unknown device type: %s", device_type)
            return None

    async def _on_device_data(self, port: str, data_type: str, payload: Dict[str, Any]) -> None:
        if self.view:
            self.view.on_device_data(port, data_type, payload)

    async def _on_xbee_status_change(self, status: str, detail: str) -> None:
        """Handle XBee dongle status changes."""
        self.logger.info("XBee dongle status change: %s %s", status, detail)
        if self.view:
            self.view.on_xbee_dongle_status_change(status, detail)

    # ------------------------------------------------------------------
    # XBee Wireless Communication

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
        self.logger.debug("Requesting XBee send to %s: %s", node_id, data[:50])
        StatusMessage.send_xbee_data(node_id, data)
        # Can't know result immediately - it's async through the command protocol
        return True

    # ------------------------------------------------------------------
    # Recording control

    async def _start_recording(self) -> bool:
        self.logger.debug("_start_recording called, handlers: %s", list(self.handlers.keys()))
        if not self.handlers:
            self.logger.error("Cannot start recording - no devices connected")
            return False

        successes = []
        failures = []
        for port, handler in self.handlers.items():
            self.logger.debug("Calling start_experiment on handler for %s", port)
            handler._trial_label = self.trial_label
            try:
                started = await handler.start_experiment()
                self.logger.debug("start_experiment returned %s for %s", started, port)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.error("start_experiment failed on %s: %s", port, exc)
                started = False
            if started:
                successes.append((port, handler))
            else:
                failures.append(port)

        if failures:
            self.logger.error("Failed to start recording on: %s", ", ".join(failures))
            for port, handler in successes:
                try:
                    await handler.stop_experiment()
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.warning("Rollback stop_experiment failed on %s: %s", port, exc)
            return False

        self._recording_active = True
        if self.view:
            self.view.update_recording_state()
        return True

    async def _stop_recording(self) -> None:
        if not self._recording_active:
            return

        failures = []
        for port, handler in self.handlers.items():
            # Clear trial label when stopping
            handler._trial_label = ""
            try:
                stopped = await handler.stop_experiment()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.error("stop_experiment failed on %s: %s", port, exc)
                stopped = False
            if not stopped:
                failures.append(port)

        if failures:
            self.logger.error("Failed to stop recording on: %s", ", ".join(failures))
        self._recording_active = False
        self.trial_label = ""
        if self.view:
            self.view.update_recording_state()

    # ------------------------------------------------------------------
    # Session helpers

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
            handler.update_output_dir(self.module_data_dir)

        # Sync to model if requested
        if update_model:
            self._suppress_session_event = True
            self.model.session_dir = self.session_dir
            self._suppress_session_event = False

    # ------------------------------------------------------------------
    # GUI-facing helpers

    def get_device_handler(self, device_id: str) -> Optional[BaseDRTHandler]:
        """Get handler for a specific device."""
        return self.handlers.get(device_id)

    def get_device_type(self, device_id: str) -> Optional[DRTDeviceType]:
        """Get device type for a specific device."""
        return self.device_types.get(device_id)

    @property
    def recording(self) -> bool:
        """Whether recording is active."""
        return self._recording_active

    # ------------------------------------------------------------------
    # Window visibility control

    def _show_window(self) -> None:
        """Show the DRT window (called when main logger sends show_window command)."""
        if self.view and hasattr(self.view, '_stub_view'):
            stub_view = self.view._stub_view
            if hasattr(stub_view, 'show_window'):
                stub_view.show_window()
                self.logger.info("DRT window shown")

    def _hide_window(self) -> None:
        """Hide the DRT window (called when main logger sends hide_window command)."""
        if self.view and hasattr(self.view, '_stub_view'):
            stub_view = self.view._stub_view
            if hasattr(stub_view, 'hide_window'):
                stub_view.hide_window()
                self.logger.info("DRT window hidden")

    # ------------------------------------------------------------------
    # Utility methods

    def _coerce_trial_number(self, value: Any) -> int:
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
