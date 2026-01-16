"""Audio application coordinator."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.core.logging_utils import ensure_structured_logger

from vmc.runtime import RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard

from ..config import AudioSettings
from ..domain import AudioDeviceInfo, AudioState
from ..services import RecorderService, SessionService
from ..ui import AudioView
from .command_router import CommandRouter
from .device_manager import DeviceManager
from .module_bridge import ModuleBridge
from .recording_manager import RecordingManager


class AudioApp:
    """Audio module coordinator."""
    def __init__(
        self,
        context: RuntimeContext,
        settings: AudioSettings,
        *,
        status_callback: Callable[[StatusType, dict[str, Any]], None] | None = None,
    ) -> None:
        self.context = context
        self.settings = settings
        base_logger = ensure_structured_logger(getattr(context, "logger", None), fallback_name="Audio")
        self.logger = base_logger.getChild("App")
        level_name = getattr(self.settings, "log_level", "debug")
        desired_level = getattr(logging, str(level_name).upper(), logging.DEBUG)
        self.logger.setLevel(desired_level)
        self.module_model = context.model
        self.status_callback = status_callback or StatusMessage.send

        self.state = AudioState()
        self.task_manager = BackgroundTaskManager("AudioTasks", self.logger)
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=settings.shutdown_timeout)
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

        self.logger.debug("AudioApp initialized: sample_rate=%d, shutdown_timeout=%.1fs",
                          settings.sample_rate, settings.shutdown_timeout)

        self._stop_event = asyncio.Event()
        self._pending_trial = 1

        self.module_bridge = ModuleBridge(
            self.module_model,
            self.logger,
            on_recording_change=self._handle_bridge_recording_event,
            on_trial_change=self._handle_bridge_trial_event,
            on_session_change=self._handle_bridge_session_event,
        )

        self.device_manager = DeviceManager(
            self.state,
            self.recorder_service,
            self.logger,
        )
        self.recording_manager = RecordingManager(
            self.state,
            self.recorder_service,
            self.session_service,
            self.module_bridge,
            self.logger,
            self._emit_status,
        )

        self.view = AudioView(
            context.view,
            self.state,
            submit_async=self._submit_async,
            logger=self.logger,
        )

        self.command_router = CommandRouter(self.logger, self)
        self._restore_state_from_config()

    def _restore_state_from_config(self) -> None:
        try:
            prefs = getattr(self.module_model, "preferences", None)
            if prefs is None:
                return
            audio_prefs = prefs.scope("audio")
            state_data = audio_prefs.snapshot()
            if state_data:
                self.state.restore_from_state(state_data)
        except Exception as e:
            self.logger.warning("Failed to restore audio state: %s", e)

    async def _save_state_to_config(self) -> None:
        try:
            prefs = getattr(self.module_model, "preferences", None)
            if prefs is None:
                return
            state_data = self.state.get_persistable_state()
            if not state_data:
                return
            prefixed = {f"audio.{k}": v for k, v in state_data.items()}
            await prefs.write_async(prefixed)
        except Exception as e:
            self.logger.warning("Failed to save audio state: %s", e)

    async def start(self) -> None:
        self.logger.info("Audio module started (waiting for device assignments)")
        if self.view.enabled:
            self.task_manager.create(self._meter_refresh_loop(), name="meter_refresh")

    async def shutdown(self) -> None:
        await self.shutdown_guard.start()
        await self.stop_recording()
        await self._save_state_to_config()
        self._stop_event.set()
        await self.task_manager.shutdown()
        await self.recorder_service.stop_all()
        await self.shutdown_guard.cancel()
        self.logger.info("Audio shutdown complete")

    async def handle_command(self, command: dict[str, Any]) -> bool:
        return await self.command_router.handle_command(command)

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.command_router.handle_user_action(action, **kwargs)

    async def healthcheck(self) -> bool:
        if self.state.recording:
            return self.recorder_service.any_recording_active
        return not self._stop_event.is_set()

    async def enable_device(self, device: AudioDeviceInfo) -> bool:
        return await self.device_manager.enable_device(device)

    async def disable_device(self) -> bool:
        return await self.device_manager.disable_device()

    async def start_recording(self, trial_number: int | None = None, trial_label: str = "") -> bool:
        if trial_number is None:
            trial_number = self._pending_trial
        started = await self.recording_manager.start(trial_number, trial_label)
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

    def _submit_async(self, coro: Awaitable[None], name: str) -> asyncio.Task:
        return self.task_manager.create(coro, name=name)

    async def _meter_refresh_loop(self) -> None:
        interval = max(0.05, self.settings.meter_refresh_interval)
        while not self._stop_event.is_set():
            await asyncio.sleep(interval)
            self.view.draw_level_meters()

    def _handle_bridge_recording_event(self, active: bool) -> None:
        if active:
            self.task_manager.create(self.start_recording(), name="recording_from_bridge")
        else:
            self.task_manager.create(self.stop_recording(), name="stop_from_bridge")

    def _handle_bridge_trial_event(self, value: Any) -> None:
        try:
            self._pending_trial = max(1, int(value))
        except (TypeError, ValueError):
            self._pending_trial = 1

    def _handle_bridge_session_event(self, value: Any) -> None:
        if not value:
            self.state.set_session_dir(None)
            return
        try:
            path = Path(value)
        except TypeError:
            return
        self.state.set_session_dir(path)

    def _emit_status(self, status_type: StatusType, payload: dict[str, Any]) -> None:
        try:
            self.status_callback(status_type, payload)
        except Exception:
            self.logger.debug("Status callback failed", exc_info=True)
