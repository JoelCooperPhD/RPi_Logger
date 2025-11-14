"""Refactored audio application composed of small managers."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from rpi_logger.core.commands import StatusMessage, StatusType

from vmc.runtime import RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard

from ..config import AudioSettings
from ..domain import AudioState
from ..services import DeviceDiscoveryService, RecorderService, SessionService
from ..ui import AudioView, ViewCallbacks
from .command_router import CommandRouter
from .device_manager import DeviceManager
from .module_bridge import ModuleBridge
from .recording_manager import RecordingManager
from .startup import AudioStartupManager


class AudioApp:
    """High-level coordinator for the audio module."""

    def __init__(
        self,
        context: RuntimeContext,
        settings: AudioSettings,
        *,
        status_callback: Callable[[StatusType, Dict[str, Any]], None] | None = None,
    ) -> None:
        self.context = context
        self.settings = settings
        base_logger = context.logger or logging.getLogger("Audio")
        self.logger = base_logger.getChild("App")
        level_name = getattr(self.settings, "log_level", "debug")
        desired_level = getattr(logging, str(level_name).upper(), logging.DEBUG)
        self.logger.setLevel(desired_level)
        self.module_model = context.model
        self.status_callback = status_callback or StatusMessage.send

        self.state = AudioState()
        self.task_manager = BackgroundTaskManager("AudioTasks", self.logger)
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

        self.module_bridge = ModuleBridge(
            self.module_model,
            self.logger,
            on_recording_change=self._handle_bridge_recording_event,
            on_trial_change=self._handle_bridge_trial_event,
            on_session_change=self._handle_bridge_session_event,
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
            self.module_bridge,
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

        self.view = AudioView(
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

    def _handle_bridge_recording_event(self, active: bool) -> None:
        self.logger.debug("Bridge set recording=%s", active)
        if active:
            self.task_manager.create(self.start_recording(), name="recording_from_bridge")
        else:
            self.task_manager.create(self.stop_recording(), name="stop_from_bridge")

    def _handle_bridge_trial_event(self, value: Any) -> None:
        try:
            self._pending_trial = max(1, int(value))
            self.logger.debug("Bridge set trial number to %d", self._pending_trial)
        except (TypeError, ValueError):
            self._pending_trial = 1
            self.logger.debug("Bridge trial value %r invalid; reset to 1", value)

    def _handle_bridge_session_event(self, value: Any) -> None:
        if not value:
            return
        try:
            path = Path(value)
        except TypeError:
            self.logger.debug("Bridge session value %r invalid; ignoring", value)
            return
        self.state.set_session_dir(path)
        self.logger.debug("Bridge session directory updated to %s", path)

    def _emit_status(self, status_type: StatusType, payload: Dict[str, Any]) -> None:
        try:
            self.status_callback(status_type, payload)
        except Exception:
            self.logger.debug("Status callback failed", exc_info=True)
