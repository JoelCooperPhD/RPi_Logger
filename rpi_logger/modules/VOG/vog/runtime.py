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
from rpi_logger.modules.base.usb_serial_manager import (
    USBDeviceConfig,
    USBDeviceMonitor,
    USBSerialDevice,
)
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir
from rpi_logger.modules.VOG.vog_core.config.config_loader import load_config_file
from rpi_logger.modules.VOG.vog_core.vog_handler import VOGHandler
from rpi_logger.modules.VOG.vog_core.protocols import SVOGProtocol, WVOGProtocol
from rpi_logger.modules.VOG.vog_core.constants import (
    SVOG_VID, SVOG_PID, SVOG_BAUD,
    WVOG_VID, WVOG_PID, WVOG_BAUD,
    determine_device_type_from_vid_pid,
)


def _determine_device_type(device: USBSerialDevice) -> str:
    """Determine device type from VID/PID.

    Wrapper around shared utility function that extracts VID/PID from device.
    """
    config = getattr(device, 'config', None)
    if config:
        vid = getattr(config, 'vid', None)
        pid = getattr(config, 'pid', None)
    else:
        vid = getattr(device, 'vid', None)
        pid = getattr(device, 'pid', None)

    return determine_device_type_from_vid_pid(vid, pid)


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
        self.usb_monitors: Dict[str, USBDeviceMonitor] = {}

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
        """Start the runtime - initialize USB monitors and bind to view/model."""
        self.logger.info("Starting VOG runtime")
        self._loop = asyncio.get_running_loop()

        # Bind to view if available
        if self.view:
            self.view.bind_runtime(self)

        # Initialize session directory
        await self._ensure_session_dir(self.model.session_dir)

        # Subscribe to model changes
        self.model.subscribe(self._on_model_change)

        # Start USB monitors for both device types
        await self._start_usb_monitors()
        self.logger.info("VOG runtime ready; waiting for devices")

    async def shutdown(self) -> None:
        """Shutdown the runtime - stop session and USB monitors."""
        self.logger.info("Shutting down VOG runtime")
        await self._stop_session()  # This also stops recording if active
        await self._stop_usb_monitors()

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
    # USB monitor management
    # ------------------------------------------------------------------

    async def _start_usb_monitors(self) -> None:
        """Start USB monitors for both sVOG and wVOG devices."""
        # sVOG monitor (wired Teensy-based device)
        svog_config = USBDeviceConfig(
            vid=SVOG_VID,
            pid=SVOG_PID,
            baudrate=SVOG_BAUD,
            device_name="sVOG",
        )
        svog_monitor = USBDeviceMonitor(
            config=svog_config,
            on_connect=self._on_device_connected,
            on_disconnect=self._on_device_disconnected,
        )
        await svog_monitor.start()
        self.usb_monitors['svog'] = svog_monitor
        self.logger.info("Started USB monitor for sVOG (VID=0x%04X, PID=0x%04X)", SVOG_VID, SVOG_PID)

        # wVOG monitor (wireless/USB MicroPython-based device)
        wvog_config = USBDeviceConfig(
            vid=WVOG_VID,
            pid=WVOG_PID,
            baudrate=WVOG_BAUD,
            device_name="wVOG",
        )
        wvog_monitor = USBDeviceMonitor(
            config=wvog_config,
            on_connect=self._on_device_connected,
            on_disconnect=self._on_device_disconnected,
        )
        await wvog_monitor.start()
        self.usb_monitors['wvog'] = wvog_monitor
        self.logger.info("Started USB monitor for wVOG (VID=0x%04X, PID=0x%04X)", WVOG_VID, WVOG_PID)

    async def _stop_usb_monitors(self) -> None:
        """Stop all USB monitors."""
        for device_type, monitor in list(self.usb_monitors.items()):
            self.logger.debug("Stopping USB monitor for %s", device_type)
            await monitor.stop()
        self.usb_monitors.clear()

    # ------------------------------------------------------------------
    # Device events
    # ------------------------------------------------------------------

    async def _on_device_connected(self, device: USBSerialDevice) -> None:
        """Handle USB device connection."""
        port = device.port
        device_type = _determine_device_type(device)
        self.logger.info("%s connected on %s", device_type.upper(), port)

        # Create appropriate protocol
        protocol = WVOGProtocol() if device_type == 'wvog' else SVOGProtocol()

        # Create handler
        handler = VOGHandler(device, port, self.module_data_dir, system=self, protocol=protocol)
        handler.set_data_callback(self._on_device_data)

        await handler.initialize_device()
        await handler.start()

        self.handlers[port] = handler

        # Request current config from device so it's cached for config dialog
        await handler.get_device_config()

        # Notify view
        if self.view:
            self.view.on_device_connected(port, device_type)

        # If session is active, start experiment on new device
        if self._session_active:
            try:
                await handler.start_experiment()
                self.logger.info("Started experiment on newly connected device %s", port)
            except Exception as exc:
                self.logger.error("Failed to start experiment on new device %s: %s", port, exc)

        # If recording is active, also start trial
        if self._recording_active:
            try:
                await handler.start_trial()
                self.logger.info("Started trial on newly connected device %s", port)
            except Exception as exc:
                self.logger.error("Failed to start trial on new device %s: %s", port, exc)

    async def _on_device_disconnected(self, port: str) -> None:
        """Handle USB device disconnection."""
        handler = self.handlers.pop(port, None)
        device_type = handler.device_type if handler else 'unknown'
        self.logger.info("%s disconnected from %s", device_type.upper(), port)

        if handler:
            await handler.stop()

        # Notify view
        if self.view:
            self.view.on_device_disconnected(port)

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

        # Sync to model if requested
        if update_model:
            self._suppress_session_event = True
            self.model.session_dir = self.session_dir
            self._suppress_session_event = False

    # ------------------------------------------------------------------
    # Public API for GUI/View
    # ------------------------------------------------------------------

    def get_device_handler(self, port: str) -> Optional[VOGHandler]:
        """Get handler for a specific port."""
        return self.handlers.get(port)

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
