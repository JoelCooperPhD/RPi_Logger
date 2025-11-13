"""Refactored audio stub application composed of small managers."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional

from logger_core.commands import StatusMessage, StatusType

from vmc.runtime import RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard

from .config import AudioStubSettings
from .services import DeviceDiscoveryService, RecorderService, SessionService
from .startup import AudioStartupManager
from .state import AudioDeviceInfo, AudioState
from .view import AudioStubView, ViewCallbacks


class AudioApp:
    """High-level coordinator for the audio stub module."""

    def __init__(
        self,
        context: RuntimeContext,
        settings: AudioStubSettings,
        *,
        status_callback: Callable[[StatusType, Dict[str, Any]], None] | None = None,
    ) -> None:
        self.context = context
        self.settings = settings
        base_logger = context.logger or logging.getLogger("AudioStub")
        self.logger = base_logger.getChild("App")
        self.logger.setLevel(logging.DEBUG)
        self.stub_model = context.model
        self.status_callback = status_callback or StatusMessage.send

        self.state = AudioState()
        self.task_manager = BackgroundTaskManager("AudioStubTasks", self.logger)
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=settings.shutdown_timeout)
        self.device_service = DeviceDiscoveryService(self.logger, settings.sample_rate)
        self.recorder_service = RecorderService(
            self.logger,
            settings.sample_rate,
            settings.recorder_start_timeout,
            settings.recorder_stop_timeout,
        )
        self.session_service = SessionService(
            settings.output_dir,
            settings.session_prefix,
            self.logger,
        )

        self.logger.debug("Initialized AudioApp with settings: %s", settings)

        self._stop_event = asyncio.Event()
        self._pending_trial = 1

        self.stub_bridge = StubBridge(
            self.stub_model,
            self.logger,
            on_recording_change=self._handle_stub_recording_event,
            on_trial_change=self._handle_stub_trial_event,
            on_session_change=self._handle_stub_session_event,
        )

        self.device_manager = DeviceManager(
            self.state,
            self.device_service,
            self.recorder_service,
            self.logger,
        )
        self.recording_manager = RecordingManager(
            self.state,
            self.recorder_service,
            self.session_service,
            self.stub_bridge,
            self.logger,
            self._emit_status,
        )
        self.startup_manager = AudioStartupManager(
            context,
            self.state,
            task_submitter=self._submit_async,
            logger=self.logger,
        )
        self.startup_manager.bind()

        self.view = AudioStubView(
            context.view,
            self.state,
            callbacks=ViewCallbacks(toggle_device=self.toggle_device),
            submit_async=self._submit_async,
            logger=self.logger,
            mode=settings.mode,
        )

        self.command_router = CommandRouter(self.logger, self)

    # ------------------------------------------------------------------
    # Lifecycle

    async def start(self) -> None:
        self.logger.debug(
            "start() invoked (auto_select_new=%s, auto_start_recording=%s)",
            self.settings.auto_select_new,
            self.settings.auto_start_recording,
        )
        await self.recording_manager.ensure_session_dir(self.state.session_dir)
        devices, new_ids = await self.device_manager.discover_devices()
        await self.startup_manager.restore_previous_selection(self.device_manager)
        if devices:
            self.logger.info(
                "Discovered %d audio device(s) (%d new)",
                len(devices),
                len(new_ids),
            )
        else:
            self.logger.warning("No audio devices discovered")

        if self.settings.auto_select_new and not self.state.selected_devices:
            if new_ids:
                self.logger.info("Auto-selecting %d new device(s)", len(new_ids))
                await self.device_manager.auto_select(new_ids)
            else:
                self.logger.debug("Auto-select enabled; selecting first available device")
                await self.device_manager.auto_select_first_available()

        if self.settings.auto_start_recording:
            self.logger.info("Auto-start recording enabled; starting trial %d", self._pending_trial)
            await self.start_recording()

        self.task_manager.create(self._device_poll_loop(), name="device_poll")
        self.logger.debug("Device poll loop scheduled")
        if self.view.enabled:
            self.task_manager.create(self._meter_refresh_loop(), name="meter_refresh")
            self.logger.debug("Meter refresh loop scheduled (view enabled)")

    async def shutdown(self) -> None:
        self.logger.debug("Shutdown requested")
        await self.shutdown_guard.start()
        await self.stop_recording()
        await self.startup_manager.flush()
        self._stop_event.set()
        await self.task_manager.shutdown()
        await self.recorder_service.stop_all()
        await self.shutdown_guard.cancel()
        self.logger.info("Audio app shutdown complete")

    # ------------------------------------------------------------------
    # Command/user handling

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        return await self.command_router.handle_command(command)

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.command_router.handle_user_action(action, **kwargs)

    async def healthcheck(self) -> bool:
        if self.state.recording:
            return self.recorder_service.any_recording_active
        return not self._stop_event.is_set()

    # ------------------------------------------------------------------
    # Public helpers exposed to managers/commands

    async def toggle_device(self, device_id: int, enabled: bool) -> None:
        await self.device_manager.toggle_device(device_id, enabled)

    async def start_recording(self, trial_number: Optional[int] = None) -> bool:
        if trial_number is None:
            trial_number = self._pending_trial
        selected_ids = list(self.state.selected_devices.keys())
        started = await self.recording_manager.start(selected_ids, trial_number)
        if started:
            self._pending_trial = trial_number + 1
        return started

    @property
    def pending_trial_number(self) -> int:
        return self._pending_trial

    async def stop_recording(self) -> bool:
        return await self.recording_manager.stop()

    async def ensure_session_dir(self) -> Path:
        return await self.recording_manager.ensure_session_dir(self.state.session_dir)

    # ------------------------------------------------------------------
    # Internal helpers

    def _submit_async(self, coro: Awaitable[None], name: str) -> asyncio.Task:
        return self.task_manager.create(coro, name=name)

    async def _device_poll_loop(self) -> None:
        interval = max(1.0, float(self.settings.discovery_retry or self.settings.device_scan_interval))
        self.logger.debug("Device poll loop running every %.2fs", interval)
        while not self._stop_event.is_set():
            await asyncio.sleep(interval)
            _, new_ids = await self.device_manager.discover_devices()
            if self.settings.auto_select_new and new_ids:
                await self.device_manager.auto_select(new_ids)

    async def _meter_refresh_loop(self) -> None:
        interval = max(0.05, self.settings.meter_refresh_interval)
        self.logger.debug("Meter refresh loop running every %.2fs", interval)
        while not self._stop_event.is_set():
            await asyncio.sleep(interval)
            self.view.draw_level_meters()

    def _handle_stub_recording_event(self, active: bool) -> None:
        self.logger.debug("Stub bridge set recording=%s", active)
        if active:
            self.task_manager.create(self.start_recording(), name="recording_from_stub")
        else:
            self.task_manager.create(self.stop_recording(), name="stop_from_stub")

    def _handle_stub_trial_event(self, value: Any) -> None:
        try:
            self._pending_trial = max(1, int(value))
            self.logger.debug("Stub bridge set trial number to %d", self._pending_trial)
        except (TypeError, ValueError):
            self._pending_trial = 1
            self.logger.debug("Stub trial value %r invalid; reset to 1", value)

    def _handle_stub_session_event(self, value: Any) -> None:
        if not value:
            return
        try:
            path = Path(value)
        except TypeError:
            self.logger.debug("Stub session value %r invalid; ignoring", value)
            return
        self.state.set_session_dir(path)
        self.logger.debug("Stub session directory updated to %s", path)

    def _emit_status(self, status_type: StatusType, payload: Dict[str, Any]) -> None:
        try:
            self.status_callback(status_type, payload)
        except Exception:
            self.logger.debug("Status callback failed", exc_info=True)


# ---------------------------------------------------------------------------
# Managers and bridges


class DeviceManager:
    """Manage discovery and enable/disable of audio devices."""

    def __init__(
        self,
        state: AudioState,
        discovery_service: DeviceDiscoveryService,
        recorder_service: RecorderService,
        logger: logging.Logger,
    ) -> None:
        self.state = state
        self.discovery_service = discovery_service
        self.recorder_service = recorder_service
        self.logger = logger.getChild("DeviceManager")

    async def discover_devices(self) -> tuple[Dict[int, AudioDeviceInfo], set[int]]:
        devices = await asyncio.to_thread(self.discovery_service.list_input_devices)
        previous_ids = set(self.state.devices.keys())
        self.state.set_devices(devices)

        removed = previous_ids - set(devices.keys())
        for missing in removed:
            await self.recorder_service.disable_device(missing)

        new_ids = set(devices.keys()) - previous_ids
        if removed:
            self.logger.info("Removed %d missing device(s): %s", len(removed), sorted(removed))
        self.logger.debug(
            "Discovery result: %d devices (%d new, %d removed)",
            len(devices),
            len(new_ids),
            len(removed),
        )
        return devices, new_ids

    async def toggle_device(self, device_id: int, enabled: bool) -> None:
        self.logger.debug("Toggle requested for device %d (enabled=%s)", device_id, enabled)
        devices = self.state.devices
        if device_id not in devices:
            self.logger.info("Toggle ignored for missing device %s", device_id)
            return

        if enabled:
            device = devices[device_id]
            meter = self.state.ensure_meter(device_id)
            already_selected = device_id in self.state.selected_devices
            if not already_selected:
                self.state.select_device(device)
            success = await self.recorder_service.enable_device(device, meter)
            if not success:
                self.logger.warning(
                    "Device %s (%d) failed to start streaming",
                    device.name,
                    device.device_id,
                )
                return
            self.logger.info("Device %s (%d) enabled", device.name, device.device_id)
        else:
            self.state.deselect_device(device_id)
            await self.recorder_service.disable_device(device_id)
            self.logger.info("Device %d disabled", device_id)

    async def auto_select(self, device_ids: Iterable[int]) -> None:
        ordered = tuple(sorted(device_ids))
        if ordered:
            self.logger.info("Auto-selecting device(s): %s", ordered)
        for device_id in sorted(device_ids):
            await self.toggle_device(device_id, True)

    async def auto_select_first_available(self) -> None:
        if not self.state.devices:
            return
        first = min(self.state.devices.keys())
        self.logger.info("Auto-selecting first available device: %d", first)
        await self.toggle_device(first, True)


class RecordingManager:
    """Orchestrate session creation and recorder lifecycle."""

    def __init__(
        self,
        state: AudioState,
        recorder_service: RecorderService,
        session_service: SessionService,
        stub_bridge: "StubBridge",
        logger: logging.Logger,
        status_callback: Callable[[StatusType, Dict[str, Any]], None],
    ) -> None:
        self.state = state
        self.recorder_service = recorder_service
        self.session_service = session_service
        self.stub_bridge = stub_bridge
        self.logger = logger.getChild("RecordingManager")
        self._emit_status = status_callback
        self._active_session_dir: Path | None = None
        self._start_lock = asyncio.Lock()

    async def ensure_session_dir(self, current: Optional[Path]) -> Path:
        session_dir = await self.session_service.ensure_session_dir(current)
        self._active_session_dir = session_dir
        self.stub_bridge.set_session_dir(session_dir)
        self.state.set_session_dir(session_dir)
        return session_dir

    async def start(self, device_ids: list[int], trial_number: int) -> bool:
        self.logger.debug(
            "Recording start requested for trial %d with devices %s",
            trial_number,
            device_ids,
        )
        if self.state.recording or self._start_lock.locked():
            self.logger.debug("Recording already active or starting")
            return False
        async with self._start_lock:
            if self.state.recording:
                self.logger.debug("Recording already active inside lock")
                return False
            if not device_ids:
                self.logger.warning("No devices selected for recording")
                return False

            session_dir = await self.ensure_session_dir(self.state.session_dir)
            started = await self.recorder_service.begin_recording(device_ids, session_dir, trial_number)
            if started == 0:
                self.logger.error("No recorders ready; aborting start")
                return False

            self.state.set_recording(True, trial_number)
            self.stub_bridge.set_recording(True, trial_number)
            self._emit_status(
                StatusType.RECORDING_STARTED,
                {
                    "trial_number": trial_number,
                    "devices": started,
                    "session_dir": str(session_dir),
                },
            )
            self.logger.info(
                "Recording started for trial %d (%d device%s)",
                trial_number,
                started,
                "s" if started != 1 else "",
            )
            return True

    async def stop(self) -> bool:
        self.logger.debug("Recording stop requested (active=%s)", self.state.recording)
        if not self.state.recording:
            return False

        recordings = await self.recorder_service.finish_recording()
        trial = self.state.trial_number
        self.state.set_recording(False, trial)
        self.stub_bridge.set_recording(False, trial)

        session_dir = self._active_session_dir or self.state.session_dir
        payload = {
            "trial_number": trial,
            "recordings": [str(path) for path in recordings],
            "session_dir": str(session_dir) if session_dir else None,
        }
        self._emit_status(StatusType.RECORDING_STOPPED, payload)
        self.logger.info(
            "Recording stopped (%d file%s)",
            len(recordings),
            "s" if len(recordings) != 1 else "",
        )
        return True


class CommandRouter:
    """Routes commands/user actions to the appropriate manager."""

    def __init__(self, logger: logging.Logger, app: AudioApp) -> None:
        self.logger = logger.getChild("CommandRouter")
        self.app = app

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        self.logger.debug("Handling command: %s", action)
        if action == "start_recording":
            trial = int(command.get("trial_number", self.app.pending_trial_number))
            await self.app.start_recording(trial)
            return True
        if action == "stop_recording":
            await self.app.stop_recording()
            return True
        if action == "get_status":
            self.app._emit_status(StatusType.STATUS_REPORT, self.app.state.status_payload())
            return True
        if action == "start_session":
            await self.app.ensure_session_dir()
            return True
        self.logger.debug("Unhandled command: %s", action)
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        action = (action or "").lower()
        self.logger.debug("Handling user action: %s", action)
        if action == "start_recording":
            await self.app.start_recording()
            return True
        if action == "stop_recording":
            await self.app.stop_recording()
            return True
        if action == "toggle_device":
            device_id = kwargs.get("device_id")
            enabled = bool(kwargs.get("enabled", True))
            if isinstance(device_id, int):
                await self.app.toggle_device(device_id, enabled)
                return True
        self.logger.debug("Unhandled user action: %s", action)
        return False


class StubBridge:
    """Synchronize derived state with the stub codex shared model."""

    def __init__(
        self,
        stub_model,
        logger: logging.Logger,
        *,
        on_recording_change: Callable[[bool], None],
        on_trial_change: Callable[[Any], None],
        on_session_change: Callable[[Any], None],
    ) -> None:
        self.stub_model = stub_model
        self.logger = logger.getChild("StubBridge")
        self._suppress_recording = False
        self._suppress_trial = False
        self._suppress_session = False
        self._on_recording_change = on_recording_change
        self._on_trial_change = on_trial_change
        self._on_session_change = on_session_change
        if hasattr(self.stub_model, "subscribe"):
            self.stub_model.subscribe(self._handle_stub_event)

    def set_recording(self, active: bool, trial: Optional[int] = None) -> None:
        self._suppress_recording = True
        try:
            self.stub_model.recording = active
        finally:
            self._suppress_recording = False
        if trial is not None:
            self.set_trial_number(trial)

    def set_trial_number(self, trial: int) -> None:
        self._suppress_trial = True
        try:
            self.stub_model.trial_number = trial
        finally:
            self._suppress_trial = False

    def set_session_dir(self, path: Path) -> None:
        self._suppress_session = True
        try:
            self.stub_model.session_dir = path
        finally:
            self._suppress_session = False

    def _handle_stub_event(self, prop: str, value: Any) -> None:
        if prop == "recording":
            if self._suppress_recording:
                return
            self._on_recording_change(bool(value))
        elif prop == "trial_number":
            if self._suppress_trial:
                return
            self._on_trial_change(value)
        elif prop == "session_dir":
            if self._suppress_session:
                return
            self._on_session_change(value)
