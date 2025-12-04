"""VOG module runtime for VMC integration.

This module provides the VMC-compatible runtime that wraps VOGSystem's
core functionality with VMC model binding, view binding, and command dispatch.
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
from rpi_logger.modules.VOG.vog_core.connection_manager import ConnectionManager
from rpi_logger.modules.VOG.vog_core.device_types import VOGDeviceType


class VOGModuleRuntime(ModuleRuntime):
    """VMC-compatible runtime for VOG module.

    This runtime manages USB devices, handlers, and provides the bridge between
    the VOG core functionality and the VMC framework (model binding, view binding,
    command dispatch).

    The core session/trial control logic is shared with VOGSystem through similar
    patterns. Key differences from standalone VOGSystem:
    - Observes VMC model changes for recording state
    - Notifies VMC view of device events
    - Handles VMC commands (start_recording, stop_recording, peek_open, etc.)
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

        # Device management
        self.handlers: Dict[str, VOGHandler] = {}
        self.device_types: Dict[str, VOGDeviceType] = {}
        self.connection_manager: Optional[ConnectionManager] = None

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
        """Start the runtime - initialize connection manager and bind to view/model."""
        self.logger.info("Starting VOG runtime (all device types: sVOG, wVOG USB, wVOG wireless)")
        self._loop = asyncio.get_running_loop()

        # Bind to view if available
        if self.view:
            self.view.bind_runtime(self)

        # Initialize session directory
        await self._ensure_session_dir(self.model.session_dir)

        # Subscribe to model changes
        self.model.subscribe(self._on_model_change)

        # Start connection manager for all device types
        await self._start_connection_manager()
        self.logger.info("VOG runtime ready; scanning for devices")

    async def shutdown(self) -> None:
        """Shutdown the runtime - stop session and connection manager."""
        self.logger.info("Shutting down VOG runtime")
        await self._stop_session()  # This also stops recording if active
        await self._stop_connection_manager()

    async def cleanup(self) -> None:
        """Final cleanup - shutdown background tasks."""
        await self.task_manager.shutdown()
        self.logger.info("VOG runtime cleanup complete")

    # ------------------------------------------------------------------
    # Command and action handling (VMC ModuleRuntime interface)
    # ------------------------------------------------------------------

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        """Handle VMC commands."""
        action = (command.get("command") or "").lower()

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
    # Connection manager
    # ------------------------------------------------------------------

    async def _start_connection_manager(self) -> None:
        """Start the connection manager for all device types."""
        self.connection_manager = ConnectionManager(
            output_dir=self.module_data_dir,
            scan_interval=1.0,
            enable_xbee=True
        )
        self.connection_manager.on_device_connected = self._on_device_connected
        self.connection_manager.on_device_disconnected = self._on_device_disconnected
        self.connection_manager.on_xbee_status_change = self._on_xbee_status_change
        await self.connection_manager.start()

        # Sync XBee dongle state after start (in case already connected)
        if self.connection_manager.xbee_connected:
            port = self.connection_manager.xbee_port or ""
            self.logger.info("XBee dongle already connected on %s, syncing view", port)
            await self._on_xbee_status_change('connected', port)

    async def _stop_connection_manager(self) -> None:
        """Stop the connection manager."""
        manager = self.connection_manager
        self.connection_manager = None
        if manager:
            await manager.stop()

    # ------------------------------------------------------------------
    # Device events
    # ------------------------------------------------------------------

    async def _on_device_connected(
        self,
        device_id: str,
        device_type: VOGDeviceType,
        handler: VOGHandler
    ) -> None:
        """Handle device connection from ConnectionManager."""
        self.logger.info("%s connected: %s", device_type.value, device_id)

        # Set up system reference and data callback
        handler.system = self
        handler.set_data_callback(self._on_device_data)

        # Store handler and type
        self.handlers[device_id] = handler
        self.device_types[device_id] = device_type

        # Notify view
        if self.view:
            self.view.on_device_connected(device_id, device_type)

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

    async def _on_device_disconnected(self, device_id: str, device_type: VOGDeviceType) -> None:
        """Handle device disconnection from ConnectionManager."""
        self.logger.info("%s disconnected: %s", device_type.value, device_id)
        self.handlers.pop(device_id, None)
        self.device_types.pop(device_id, None)

        # Notify view
        if self.view:
            self.view.on_device_disconnected(device_id, device_type)

    async def _on_xbee_status_change(self, status: str, detail: str) -> None:
        """Handle XBee dongle status changes."""
        self.logger.info("XBee dongle status change: %s %s", status, detail)
        if self.view:
            self.view.on_xbee_dongle_status_change(status, detail)

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

        # Also update connection manager
        if self.connection_manager:
            self.connection_manager.update_output_dir(self.module_data_dir)

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

    @property
    def xbee_connected(self) -> bool:
        """Check if XBee dongle is connected."""
        return self.connection_manager is not None and self.connection_manager.xbee_connected

    @property
    def xbee_port(self) -> Optional[str]:
        """Return the XBee dongle port if connected."""
        if self.connection_manager:
            return self.connection_manager.xbee_port
        return None

    async def rescan_xbee_network(self) -> None:
        """Trigger a rescan of the XBee network."""
        if self.connection_manager:
            self.logger.info("Triggering XBee network rescan...")
            await self.connection_manager.rescan_xbee_network()

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
