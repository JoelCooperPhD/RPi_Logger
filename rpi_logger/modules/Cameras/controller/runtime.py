"""Cameras runtime built on the stub (codex) VMC stack."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional


try:
    from picamera2 import Picamera2  # type: ignore
except Exception:  # pragma: no cover - dependency optional on dev hosts
    Picamera2 = None  # type: ignore

from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard

from ..domain.model import CameraModel
from ..ui import CameraViewAdapter
from ..io.media import frame_to_image as convert_frame_to_image
from ..logging_utils import ensure_structured_logger
from .camera_setup import CameraSetupManager
from .pipeline import StorageHooks
from .services import CaptureSettingsService, TelemetryService
from .slot import CameraSlot
from .storage_manager import CameraStorageManager
from .view_manager import CameraViewManager


class CameraController(ModuleRuntime):
    """Minimal dual-camera preview atop the stub supervisor."""

    PREVIEW_SIZE = (640, 480)
    UPDATE_INTERVAL = 0.2  # seconds
    MAX_SENSOR_FPS = 60.0
    MAX_NATIVE_SIZE = (1440, 1080)
    NATIVE_ASPECT = MAX_NATIVE_SIZE[1] / MAX_NATIVE_SIZE[0]
    STORAGE_QUEUE_DEFAULT = 8
    SESSION_RETENTION_DEFAULT = 5
    MIN_FREE_SPACE_MB_DEFAULT = 512
    VIDEO_STALL_THRESHOLD = 60
    CAPTURE_SLOW_REQUEST_THRESHOLD = 0.5  # seconds
    PREVIEW_FRACTION_CHOICES = (1.0, 0.5, 1 / 3, 0.25)

    @property
    def state(self) -> CameraModel:
        return self._state

    @property
    def preview_frame_interval(self) -> float:
        return self.state.preview_frame_interval

    @preview_frame_interval.setter
    def preview_frame_interval(self, value: float) -> None:
        self.state.preview_frame_interval = value

    @property
    def save_frame_interval(self) -> float:
        return self.state.save_frame_interval

    @save_frame_interval.setter
    def save_frame_interval(self, value: float) -> None:
        self.state.save_frame_interval = value

    @property
    def save_enabled(self) -> bool:
        return self.state.save_enabled

    @save_enabled.setter
    def save_enabled(self, value: bool) -> None:
        self.state.save_enabled = value

    @property
    def capture_preferences_enabled(self) -> bool:
        return self.state.capture_preferences_enabled

    @capture_preferences_enabled.setter
    def capture_preferences_enabled(self, value: bool) -> None:
        self.state.capture_preferences_enabled = value

    @property
    def save_format(self) -> str:
        return self.state.save_format

    @save_format.setter
    def save_format(self, value: str) -> None:
        self.state.save_format = value

    @property
    def save_quality(self) -> int:
        return self.state.save_quality

    @save_quality.setter
    def save_quality(self, value: int) -> None:
        self.state.save_quality = value

    @property
    def save_stills_enabled(self) -> bool:
        return self.state.save_stills_enabled

    @save_stills_enabled.setter
    def save_stills_enabled(self, value: bool) -> None:
        self.state.save_stills_enabled = value

    @property
    def session_retention(self) -> int:
        return self.state.session_retention

    @session_retention.setter
    def session_retention(self, value: int) -> None:
        self.state.session_retention = value

    @property
    def min_free_space_mb(self) -> int:
        return self.state.min_free_space_mb

    @min_free_space_mb.setter
    def min_free_space_mb(self, value: int) -> None:
        self.state.min_free_space_mb = value

    @property
    def storage_queue_size(self) -> int:
        return self.state.storage_queue_size

    @storage_queue_size.setter
    def storage_queue_size(self, value: int) -> None:
        self.state.storage_queue_size = value

    @property
    def overlay_config(self) -> dict:
        return self.state.overlay_config

    @property
    def save_dir(self) -> Optional[Path]:
        return self.state.save_dir

    @save_dir.setter
    def save_dir(self, value: Optional[Path]) -> None:
        self.state.save_dir = value

    @property
    def session_dir(self) -> Optional[Path]:
        return self.state.session_dir

    @session_dir.setter
    def session_dir(self, value: Optional[Path]) -> None:
        self.state.session_dir = value

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        self.supervisor = context.supervisor
        self.supervisor_model = context.model
        self.view = context.view
        base_logger = ensure_structured_logger(
            context.logger,
            component="CameraController",
            fallback_name=f"{__name__}.CameraController",
        )
        self.logger = base_logger.getChild("runtime")
        self.logger.debug("CameraController initializing")
        self.display_name = context.display_name
        self.module_dir = context.module_dir
        self.picamera_cls = Picamera2

        self.task_manager = BackgroundTaskManager("CamerasTasks", self.logger)
        timeout = getattr(self.args, "shutdown_timeout", 15.0)
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=timeout)

        self._state = CameraModel(
            args=self.args,
            module_dir=self.module_dir,
            display_name=self.display_name,
            logger=self.logger,
        )

        self.view_adapter: Optional[CameraViewAdapter] = None
        if self.view is not None:
            self.view_adapter = CameraViewAdapter(
                self.view,
                args=self.args,
                preview_size=self._state.PREVIEW_SIZE,
                task_manager=self.task_manager,
                logger=self.logger,
            )

        self.view_manager = CameraViewManager(self)
        self.storage_manager = CameraStorageManager(self)
        self.telemetry = TelemetryService(self)
        self.capture_settings = CaptureSettingsService(self)
        self.setup_manager = CameraSetupManager(self)

        self._stop_event = asyncio.Event()
        self._previews: list[CameraSlot] = []
        self._active_trial_number = 0
        self._active_trial_label: str = ""
        self._storage_hooks = StorageHooks(
            save_enabled=lambda: bool(self.save_enabled),
            session_dir_provider=lambda: self.session_dir,
            save_stills_enabled=lambda: bool(self.save_stills_enabled),
            frame_to_image=lambda frame, fmt, size_hint=None: convert_frame_to_image(
                frame,
                fmt,
                size_hint=size_hint,
            ),
            resolve_video_fps=self.telemetry.resolve_video_fps,
            on_frame_written=self.telemetry.on_storage_result,
            handle_failure=self.telemetry.handle_storage_failure,
        )
        self._sensor_mode_sizes: set[tuple[int, int]] = set()
        self._sensor_mode_bit_depths: dict[tuple[int, int], int] = {}
        self._metrics_task: Optional[asyncio.Task] = None
        self._saved_count = 0
        self._storage_failure_reported = False
        self.preview_fraction = self.capture_settings.clamp_preview_fraction(
            getattr(self.args, "preview_fraction", getattr(self._state, "preview_fraction", 1.0))
        )
        setattr(self.args, "preview_fraction", self.preview_fraction)
        self.preview_stride = self.capture_settings.fraction_to_stride(self.preview_fraction)
        self.capture_settings.apply_preview_fraction()

        if self.save_enabled and self.session_dir:
            save_rate = (
                "unlimited"
                if self.save_frame_interval <= 0
                else f"{1.0 / self.save_frame_interval:.2f} fps"
            )
            self.logger.info(
                "Frame saving enabled -> %s (rate %s, format %s, stills=%s)",
                self.session_dir,
                save_rate,
                self.save_format,
                "on" if self.save_stills_enabled else "off",
            )

    async def start(self) -> None:
        if not self.view_adapter:
            self.logger.warning("GUI view unavailable; cameras runtime running headless")
            return

        max_cams = getattr(self.args, "max_cameras", 2)
        self.view_adapter.build_camera_grid(max_cams)
        self.view_adapter.install_io_metrics_panel()
        self.view_adapter.configure_capture_menu()
        self.view_manager.install_view_hooks()
        self.view_manager.sync_record_toggle()

        if self.view_adapter and self._metrics_task is None:
            self._metrics_task = self.task_manager.create(
                self.view_manager.run_metrics_loop(),
                name="CameraPipelineMetrics",
            )

        if Picamera2 is None:
            self.logger.error("Cannot initialize cameras: picamera2 missing")
            return

        await self.setup_manager.initialize_cameras()
        await self.telemetry.flush_sensor_sync()
        await self._await_first_frames(timeout=6.0)

    async def shutdown(self) -> None:
        await self.shutdown_guard.start()
        self._stop_event.set()

        await self.task_manager.shutdown()

        slots = list(self._previews)

        async def _stop_camera(slot: CameraSlot) -> None:
            camera = slot.camera
            if not camera:
                return
            try:
                await asyncio.to_thread(camera.stop)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning("Error stopping camera %s: %s", slot.index, exc)

        async def _close_camera(slot: CameraSlot) -> None:
            camera = slot.camera
            if not camera:
                return
            try:
                await asyncio.to_thread(camera.close)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning("Error closing camera %s: %s", slot.index, exc)

        stop_tasks = [_stop_camera(slot) for slot in slots]
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        close_tasks = [_close_camera(slot) for slot in slots]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._previews.clear()

        await self.shutdown_guard.cancel()

    async def cleanup(self) -> None:
        return None

    async def handle_command(self, command: dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action in {"start_recording", "stop_recording"}:
            directory = (
                command.get("session_dir")
                or command.get("directory")
                or command.get("save_directory")
                or command.get("path")
            )
            if not directory and self.supervisor_model is not None:
                supervisor_dir = getattr(self.supervisor_model, "session_dir", None)
                if supervisor_dir:
                    directory = supervisor_dir
            self.logger.info(
                "Command received -> %s (dir=%s | save_enabled=%s | session=%s)",
                action,
                directory,
                self.save_enabled,
                self.session_dir,
            )
        if action == "start_recording":
            directory = (
                command.get("session_dir")
                or command.get("directory")
                or command.get("save_directory")
                or command.get("path")
            )
            if not directory and self.supervisor_model is not None:
                supervisor_dir = getattr(self.supervisor_model, "session_dir", None)
                if supervisor_dir:
                    directory = supervisor_dir
            trial_number = self._normalize_trial_number(command.get("trial_number"))
            if trial_number is None:
                trial_number = (self._active_trial_number or 0) + 1
            self._active_trial_number = trial_number
            self._active_trial_label = str(command.get("trial_label") or "").strip()
            previously_enabled = self.save_enabled
            success = await self.storage_manager.enable_saving(directory)
            if not success:
                return False
            if not previously_enabled:
                self.logger.info("Frame saving enabled via command without interrupting preview")
            else:
                self.logger.info("Frame saving already active; updated configuration via command")
            return True
        if action == "stop_recording":
            if not self.save_enabled:
                self.logger.info("Stop recording command ignored; recording already inactive")
                return True
            await self.storage_manager.disable_saving()
            self._active_trial_label = ""
            self.logger.info("Frame saving disabled via command")
            return True
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        if action == "update_preview_settings":
            await self.capture_settings.update_preview_settings(kwargs)
            return True
        if action == "update_record_settings":
            await self.capture_settings.update_record_settings(kwargs)
            return True
        if action in {"start_recording", "stop_recording"}:
            self.logger.info(
                "Recording user actions are ignored in the cameras stub; use the logger controller."
            )
            return True
        return False

    async def healthcheck(self) -> bool:
        if not self._previews:
            return False
        return not self._stop_event.is_set()

    # ------------------------------------------------------------------
    # UI helpers

    async def _await_first_frames(self, timeout: float = 5.0) -> bool:
        if not self._previews:
            return False
        all_ready = True
        for slot in self._previews:
            event = getattr(slot, "first_frame_event", None)
            if event is None:
                continue
            if event.is_set():
                self.logger.debug("Camera %s first frame already received", slot.index)
                continue
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
                self.logger.info("Camera %s delivered first frame", slot.index)
            except asyncio.TimeoutError:
                self.logger.error(
                    "Camera %s failed to deliver a frame within %.1fs after reconfiguration",
                    slot.index,
                    timeout,
                )
                all_ready = False
        return all_ready

    def _shutdown_queue(self, queue: Optional[asyncio.Queue]) -> None:
        if not queue:
            return
        try:
            queue.put_nowait(None)  # type: ignore[arg-type]
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(None)  # type: ignore[arg-type]
            except asyncio.QueueFull:
                pass

    async def _set_capture_resolution(self, size: Optional[tuple[int, int]]) -> bool:
        if size is None:
            new_width = None
            new_height = None
            label = "native stream"
        else:
            new_width, new_height = size
            label = f"{new_width}x{new_height}"

        prev_width = getattr(self.args, "capture_width", None)
        prev_height = getattr(self.args, "capture_height", None)

        if size is not None and not self.setup_manager.is_supported_sensor_size(size):
            self.logger.warning(
                (
                    "Capture resolution %sx%s not in the sensor's advertised modes; "
                    "per the Picamera2 manual (Appendix B, 'size'), only enumerated sensor "
                    "modes are guaranteed to work. Keeping native sensor mode and downscaling "
                    "in software instead."
                ),
                size[0],
                size[1],
            )
            self.view_manager.set_status("Resolution unchanged: sensor only exposes native mode")
            return False

        if prev_width == new_width and prev_height == new_height:
            self.logger.debug("Capture resolution already %s; skipping reconfigure", label)
            return False

        setattr(self.args, "capture_width", new_width)
        setattr(self.args, "capture_height", new_height)

        self.logger.info("Capture resolution set to %s; reinitializing cameras", label)
        await self.setup_manager.reinitialize_cameras()
        ready = await self._await_first_frames(timeout=6.0)
        if ready:
            return True

        prev_label = (
            f"{prev_width}x{prev_height}"
            if prev_width and prev_height
            else "native"
        )
        self.logger.error(
            "Capture resolution %s failed to produce frames; reverting to %s",
            label,
            prev_label,
        )
        setattr(self.args, "capture_width", prev_width)
        setattr(self.args, "capture_height", prev_height)
        await self.setup_manager.reinitialize_cameras()
        await self._await_first_frames(timeout=6.0)
        return False

    @staticmethod
    def _normalize_trial_number(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            trial = int(value)
            if trial <= 0:
                return None
            return trial
        except (TypeError, ValueError):
            return None

    @property
    def current_trial_number(self) -> int:
        return self._active_trial_number or 1

    @property
    def current_trial_label(self) -> str:
        return self._active_trial_label


__all__ = ["CameraController"]
