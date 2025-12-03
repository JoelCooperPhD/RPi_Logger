"""Runtime that hosts the legacy DRT hardware stack inside the stub framework."""

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
from rpi_logger.modules.DRT.drt_core.connection_manager import ConnectionManager
from rpi_logger.modules.DRT.drt_core.device_types import DRTDeviceType
from rpi_logger.modules.DRT.drt_core.handlers import BaseDRTHandler


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
        self.handlers: Dict[str, BaseDRTHandler] = {}
        self.device_types: Dict[str, DRTDeviceType] = {}
        self.connection_manager: Optional[ConnectionManager] = None
        self.task_manager = BackgroundTaskManager(name="DRTRuntimeTasks", logger=self.logger)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._suppress_recording_event = False
        self._suppress_session_event = False
        self._recording_active = False
        self.trial_label: str = ""
        self.active_trial_number: int = 1

    # ------------------------------------------------------------------
    # Lifecycle hooks

    async def start(self) -> None:
        self.logger.info("Starting DRT runtime (all device types: sDRT, wDRT USB, wDRT wireless)")
        self._loop = asyncio.get_running_loop()

        if self.view:
            self.view.bind_runtime(self)

        await self._ensure_session_dir(self.model.session_dir)

        self.model.subscribe(self._on_model_change)

        await self._start_connection_manager()
        self.logger.info("DRT runtime ready; scanning for devices")

    async def shutdown(self) -> None:
        self.logger.info("Shutting down DRT runtime")
        await self._stop_recording()
        await self._stop_connection_manager()

    async def cleanup(self) -> None:
        await self.task_manager.shutdown()
        self.logger.info("DRT runtime cleanup complete")

    # ------------------------------------------------------------------
    # Command and action handling

    async def handle_command(self, command: Dict[str, Any]) -> bool:
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
    # Connection manager

    async def _start_connection_manager(self) -> None:
        self.connection_manager = ConnectionManager(
            output_dir=self.module_data_dir,
            scan_interval=1.0,
            enable_xbee=True
        )
        self.connection_manager.on_device_connected = self._on_device_connected
        self.connection_manager.on_device_disconnected = self._on_device_disconnected
        await self.connection_manager.start()

    async def _stop_connection_manager(self) -> None:
        manager = self.connection_manager
        self.connection_manager = None
        if manager:
            await manager.stop()

    # ------------------------------------------------------------------
    # Device events

    async def _on_device_connected(
        self,
        device_id: str,
        device_type: DRTDeviceType,
        handler: BaseDRTHandler
    ) -> None:
        self.logger.info("%s connected: %s", device_type.value, device_id)

        # Set up data callback
        handler.data_callback = self._on_device_data

        # Store handler and type
        self.handlers[device_id] = handler
        self.device_types[device_id] = device_type

        if self.view:
            self.view.on_device_connected(device_id, device_type)

        if self._recording_active:
            # Set trial label for device joining mid-recording
            handler._trial_label = self.trial_label
            try:
                await handler.start_experiment()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.error("Failed to start experiment on new device %s: %s", device_id, exc)

    async def _on_device_disconnected(self, device_id: str, device_type: DRTDeviceType) -> None:
        self.logger.info("%s disconnected: %s", device_type.value, device_id)
        self.handlers.pop(device_id, None)
        self.device_types.pop(device_id, None)
        if self.view:
            self.view.on_device_disconnected(device_id, device_type)

    async def _on_device_data(self, port: str, data_type: str, payload: Dict[str, Any]) -> None:
        if self.view:
            self.view.on_device_data(port, data_type, payload)

    # ------------------------------------------------------------------
    # Recording control

    async def _start_recording(self) -> bool:
        self.logger.debug(f"_start_recording called, handlers: {list(self.handlers.keys())}")
        if not self.handlers:
            self.logger.error("Cannot start recording - no devices connected")
            return False

        successes = []
        failures = []
        for port, handler in self.handlers.items():
            self.logger.debug(f"Calling start_experiment on handler for {port}")
            # Set trial label before starting experiment
            handler._trial_label = self.trial_label
            try:
                started = await handler.start_experiment()
                self.logger.debug(f"start_experiment returned {started} for {port}")
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
        if new_dir is None:
            self.output_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.session_dir = self.output_root / f"{self.session_prefix}_{timestamp}"
        else:
            self.session_dir = Path(new_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.module_data_dir = ensure_module_data_dir(self.session_dir, self.module_subdir)

        for handler in self.handlers.values():
            handler.update_output_dir(self.module_data_dir)

        # Also update connection manager
        if self.connection_manager:
            self.connection_manager.update_output_dir(self.module_data_dir)

        if update_model:
            self._suppress_session_event = True
            self.model.session_dir = self.session_dir
            self._suppress_session_event = False

    # ------------------------------------------------------------------
    # GUI-facing helpers

    def get_device_handler(self, device_id: str) -> Optional[BaseDRTHandler]:
        return self.handlers.get(device_id)

    def get_device_type(self, device_id: str) -> Optional[DRTDeviceType]:
        return self.device_types.get(device_id)

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
