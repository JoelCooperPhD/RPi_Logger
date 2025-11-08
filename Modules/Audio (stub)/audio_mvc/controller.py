"""Controller coordinating the audio MVC components."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from logger_core.commands import StatusMessage, StatusType

from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard
from vmc.runtime import RuntimeContext

from .config import AudioStubConfig
from .model import AudioStubModel
from .view import AudioStubView, ViewCallbacks
from .services import DeviceDiscoveryService, RecorderService, SessionService


class AudioController:
    """Owns the audio domain model, services, and UI."""

    def __init__(
        self,
        context: RuntimeContext,
        config: AudioStubConfig,
        *,
        status_callback: Callable[[StatusType, Dict[str, Any]], None] | None = None,
    ) -> None:
        self.context = context
        self.args = context.args
        self.stub_model = context.model
        self.logger = (context.logger or logging.getLogger("AudioStub")).getChild("Runtime")
        self.config = config
        self.audio_model = AudioStubModel()
        self.task_manager = BackgroundTaskManager("AudioStubTasks", self.logger)
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=config.shutdown_timeout)
        self.status_callback = status_callback or StatusMessage.send
        self.device_service = DeviceDiscoveryService(self.logger, config.sample_rate)
        self.recorder_service = RecorderService(
            self.logger,
            config.sample_rate,
            config.recorder_start_timeout,
            config.recorder_stop_timeout,
        )
        self.session_service = SessionService(config.output_dir, config.session_prefix)
        self.view = AudioStubView(
            context.view,
            self.audio_model,
            callbacks=ViewCallbacks(
                toggle_device=self.toggle_device,
                start_recording=self.start_recording,
                stop_recording=self.stop_recording,
            ),
            submit_async=self._submit_async,
            logger=self.logger,
            mode=config.mode,
        )
        self._stop_event = asyncio.Event()
        self._suppress_recording_event = False
        self._pending_trial_number = 1

        self.stub_model.subscribe(self._on_stub_model_event)

    # ------------------------------------------------------------------
    # Lifecycle

    async def start(self) -> None:
        await self._ensure_output_dir()
        await self._discover_devices(initial=True)

        if self.config.auto_select_new and not self.audio_model.selected_devices:
            await self._auto_select_first_available()

        if self.config.auto_start_recording:
            await self.start_recording()

        self.task_manager.create(self._device_poll_loop(), name="device_poll")
        if self.view.enabled:
            self.task_manager.create(self._meter_refresh_loop(), name="meter_refresh")

    async def shutdown(self) -> None:
        await self.shutdown_guard.start()
        await self.stop_recording()
        self._stop_event.set()
        await self.task_manager.shutdown()
        await self.recorder_service.stop_all()
        await self.shutdown_guard.cancel()
        self.logger.info("Audio controller shutdown complete")

    # ------------------------------------------------------------------
    # Command/user handling

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action == "start_recording":
            trial = int(command.get("trial_number", self._pending_trial_number))
            await self.start_recording(trial_number=trial)
            return True
        if action == "stop_recording":
            await self.stop_recording()
            return True
        if action == "get_status":
            self._emit_status(StatusType.STATUS_REPORT, self.audio_model.status_payload())
            return True
        if action == "start_session":
            await self._ensure_output_dir()
            return True
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        action = (action or "").lower()
        if action == "start_recording":
            await self.start_recording()
            return True
        if action == "stop_recording":
            await self.stop_recording()
            return True
        if action == "toggle_device":
            device_id = kwargs.get("device_id")
            enabled = bool(kwargs.get("enabled", True))
            if isinstance(device_id, int):
                await self.toggle_device(device_id, enabled)
                return True
        return False

    async def healthcheck(self) -> bool:
        if self.audio_model.recording:
            return any(recorder.recording for recorder in self.recorder_service.recorders.values())
        return not self._stop_event.is_set()

    # ------------------------------------------------------------------
    # View callbacks

    async def toggle_device(self, device_id: int, enabled: bool) -> None:
        devices = self.audio_model.devices
        if device_id not in devices:
            self.logger.info("Toggle ignored for missing device %s", device_id)
            return

        if enabled:
            device = devices[device_id]
            meter = self.audio_model.ensure_meter(device_id)
            success = await self.recorder_service.enable_device(device, meter)
            if success:
                self.audio_model.select_device(device)
        else:
            self.audio_model.deselect_device(device_id)
            await self.recorder_service.disable_device(device_id)

    async def start_recording(self, trial_number: Optional[int] = None) -> bool:
        if self.audio_model.recording:
            self.logger.debug("Recording already active")
            return False
        if not self.audio_model.selected_devices:
            self.logger.warning("No devices selected for recording")
            return False

        session_dir = await self._ensure_output_dir()
        trial = trial_number or self._pending_trial_number
        if trial <= 0:
            trial = 1
        self._pending_trial_number = trial + 1

        started = await self.recorder_service.begin_recording(list(self.audio_model.selected_devices.keys()))
        if started == 0:
            self.logger.error("No recorders ready; aborting start")
            return False

        self._suppress_recording_event = True
        self.stub_model.recording = True
        self.stub_model.trial_number = trial
        self.audio_model.set_recording(True, trial)
        self._emit_status(
            StatusType.RECORDING_STARTED,
            {
                "trial_number": trial,
                "devices": started,
                "session_dir": str(session_dir),
            },
        )
        self.logger.info("Recording started (%d device%s)", started, "s" if started != 1 else "")
        return True

    async def stop_recording(self) -> bool:
        if not self.audio_model.recording:
            return False

        session_dir = await self._ensure_output_dir()
        trial = self.stub_model.trial_number or self._pending_trial_number - 1
        recordings = await self.recorder_service.finish_recording(session_dir, trial)

        self._suppress_recording_event = True
        self.stub_model.recording = False
        self.stub_model.trial_number = trial
        self.audio_model.set_recording(False, trial)
        self._emit_status(
            StatusType.RECORDING_STOPPED,
            {
                "trial_number": trial,
                "recordings": [str(path) for path in recordings],
                "session_dir": str(session_dir),
            },
        )
        self.logger.info("Recording stopped (%d file%s)", len(recordings), "s" if len(recordings) != 1 else "")
        return True

    # ------------------------------------------------------------------
    # Background loops

    async def _device_poll_loop(self) -> None:
        interval = max(1.0, float(self.config.discovery_retry or self.config.device_scan_interval))
        while not self._stop_event.is_set():
            await asyncio.sleep(interval)
            await self._discover_devices()

    async def _meter_refresh_loop(self) -> None:
        interval = max(0.05, self.config.meter_refresh_interval)
        while not self._stop_event.is_set():
            await asyncio.sleep(interval)
            self.view.draw_level_meters()

    # ------------------------------------------------------------------
    # Helpers

    def _submit_async(self, coro: Awaitable[None], name: str) -> None:
        self.task_manager.create(coro, name=name)

    async def _discover_devices(self, *, initial: bool = False) -> None:
        devices = await asyncio.to_thread(self.device_service.list_input_devices)
        previous = set(self.audio_model.devices.keys())
        self.audio_model.set_devices(devices)

        removed = previous - set(devices.keys())
        for missing_id in removed:
            await self.recorder_service.disable_device(missing_id)

        if self.config.auto_select_new:
            new_ids = set(devices.keys()) - previous
            for device_id in sorted(new_ids):
                await self.toggle_device(device_id, True)

        if initial and not devices:
            self.logger.info("No audio devices discovered")

    async def _auto_select_first_available(self) -> None:
        if not self.audio_model.devices:
            return
        first_id = min(self.audio_model.devices.keys())
        await self.toggle_device(first_id, True)

    async def _ensure_output_dir(self) -> Path:
        session_dir = getattr(self.stub_model, "session_dir", None)
        session_dir = await self.session_service.ensure_session_dir(session_dir)
        self.stub_model.session_dir = session_dir
        self.audio_model.set_session_dir(session_dir)
        return session_dir

    def _emit_status(self, status_type: StatusType, payload: Dict[str, Any]) -> None:
        try:
            self.status_callback(status_type, payload)
        except Exception:
            self.logger.debug("Status callback failed", exc_info=True)

    def _on_stub_model_event(self, prop: str, value: Any) -> None:
        if prop == "recording":
            if self._suppress_recording_event:
                self._suppress_recording_event = False
                return
            if value:
                self.task_manager.create(self.start_recording(), name="recording_from_model")
            else:
                self.task_manager.create(self.stop_recording(), name="stop_from_model")
        elif prop == "trial_number" and value:
            try:
                self._pending_trial_number = max(1, int(value))
            except (TypeError, ValueError):
                self._pending_trial_number = 1
        elif prop == "session_dir" and value:
            self.audio_model.set_session_dir(Path(value))

