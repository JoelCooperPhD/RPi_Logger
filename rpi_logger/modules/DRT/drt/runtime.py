"""Runtime that hosts the legacy DRT hardware stack inside the stub framework."""

from __future__ import annotations

import asyncio
import logging
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
from rpi_logger.modules.DRT.drt_core.config import load_config_file
from rpi_logger.modules.DRT.drt_core.constants import DRT_VID, DRT_PID
from rpi_logger.modules.DRT.drt_core.drt_handler import DRTHandler


class DRTModuleRuntime(ModuleRuntime):
    """Owns USB device management and orchestrates the GUI updates."""

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        self.module_dir = context.module_dir
        self.logger = context.logger.getChild("Runtime")
        self.model = context.model
        self.controller = context.controller
        self.view = context.view
        self.display_name = context.display_name
        self.config_path = self.module_dir / "config.txt"
        self.config: Dict[str, Any] = load_config_file(self.config_path)

        self.device_vid = self._coerce_int(
            getattr(self.args, "device_vid", None) or self.config.get("device_vid"),
            DRT_VID,
        )
        self.device_pid = self._coerce_int(
            getattr(self.args, "device_pid", None) or self.config.get("device_pid"),
            DRT_PID,
        )
        self.baudrate = self._coerce_int(
            getattr(self.args, "baudrate", None) or self.config.get("baudrate"),
            9600,
        )
        self.session_prefix = str(getattr(self.args, "session_prefix", self.config.get("session_prefix", "drt")))
        self.enable_gui_commands = bool(getattr(self.args, "enable_commands", False))

        self.output_root: Path = Path(getattr(self.args, "output_dir", Path("drt_data")))
        self.session_dir: Path = self.output_root
        self.handlers: Dict[str, DRTHandler] = {}
        self.usb_monitor: Optional[USBDeviceMonitor] = None
        self.task_manager = BackgroundTaskManager(name="DRTRuntimeTasks", logger=self.logger)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._suppress_recording_event = False
        self._suppress_session_event = False
        self._recording_active = False
        self.trial_label: str = ""

    # ------------------------------------------------------------------
    # Lifecycle hooks

    async def start(self) -> None:
        self.logger.info(
            "Starting DRT runtime (VID=0x%04X PID=0x%04X baud=%d)",
            self.device_vid,
            self.device_pid,
            self.baudrate,
        )
        self._loop = asyncio.get_running_loop()

        if self.view:
            self.view.bind_runtime(self)

        await self._ensure_session_dir(self.model.session_dir)

        self.model.subscribe(self._on_model_change)

        await self._start_usb_monitor()
        self.logger.info("DRT runtime ready; waiting for devices")

    async def shutdown(self) -> None:
        self.logger.info("Shutting down DRT runtime")
        await self._stop_recording()
        await self._stop_usb_monitor()

    async def cleanup(self) -> None:
        await self.task_manager.shutdown()
        self.logger.info("DRT runtime cleanup complete")

    # ------------------------------------------------------------------
    # Command and action handling

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action == "start_recording":
            self.trial_label = str(command.get("trial_label", "") or "")
            session_dir = command.get("session_dir")
            if session_dir:
                await self._ensure_session_dir(Path(session_dir), update_model=False)
            return True
        if action == "stop_recording":
            self.trial_label = ""
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
    # USB monitor management

    async def _start_usb_monitor(self) -> None:
        config = USBDeviceConfig(
            vid=self.device_vid,
            pid=self.device_pid,
            baudrate=self.baudrate,
            device_name="sDRT",
        )
        self.usb_monitor = USBDeviceMonitor(
            config=config,
            on_connect=self._on_device_connected,
            on_disconnect=self._on_device_disconnected,
        )
        await self.usb_monitor.start()

    async def _stop_usb_monitor(self) -> None:
        monitor = self.usb_monitor
        self.usb_monitor = None
        if monitor:
            await monitor.stop()

    # ------------------------------------------------------------------
    # Device events

    async def _on_device_connected(self, device: USBSerialDevice) -> None:
        port = device.port
        self.logger.info("sDRT connected on %s", port)
        handler = DRTHandler(device, port, self.session_dir, system=self)
        handler.set_data_callback(self._on_device_data)

        await handler.initialize_device()
        await handler.start()

        self.handlers[port] = handler

        if self.view:
            self.view.on_device_connected(port)

        if self._recording_active:
            try:
                await handler.start_experiment()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.error("Failed to start experiment on new device %s: %s", port, exc)

    async def _on_device_disconnected(self, port: str) -> None:
        self.logger.info("sDRT disconnected from %s", port)
        handler = self.handlers.pop(port, None)
        if handler:
            await handler.stop()
        if self.view:
            self.view.on_device_disconnected(port)

    async def _on_device_data(self, port: str, data_type: str, payload: Dict[str, Any]) -> None:
        if self.view:
            self.view.on_device_data(port, data_type, payload)

    # ------------------------------------------------------------------
    # Recording control

    async def _start_recording(self) -> bool:
        if not self.handlers:
            self.logger.error("Cannot start recording - no devices connected")
            return False

        successes = []
        failures = []
        for port, handler in self.handlers.items():
            try:
                started = await handler.start_experiment()
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
        if new_dir is None:
            self.output_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.session_dir = self.output_root / f"{self.session_prefix}_{timestamp}"
        else:
            self.session_dir = Path(new_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        for handler in self.handlers.values():
            handler.output_dir = self.session_dir

        if update_model:
            self._suppress_session_event = True
            self.model.session_dir = self.session_dir
            self._suppress_session_event = False

    # ------------------------------------------------------------------
    # GUI-facing helpers

    def get_device_handler(self, port: str) -> Optional[DRTHandler]:
        return self.handlers.get(port)

    @property
    def recording(self) -> bool:
        return self._recording_active

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        if isinstance(value, int):
            return value
        if value is None:
            return default
        try:
            return int(str(value), 0)
        except (TypeError, ValueError):
            return default
