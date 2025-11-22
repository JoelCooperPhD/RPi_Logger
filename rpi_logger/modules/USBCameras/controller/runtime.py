"""USB Cameras runtime built on the stub (codex) VMC stack."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard

from ..domain.model import RollingFpsCounter, USBCameraModel
from ..io.media import frame_to_bgr
from .device_manager import USBCameraDiscovery
from .slot import USBCameraSlot
from .storage_manager import USBStorageManager
from .view_manager import USBViewManager
from ..pipeline import StorageHooks
from ..services import DeviceRegistry, RecordingManager, SlotManager
from ..ui import USBCameraViewAdapter

from rpi_logger.core.logging_utils import ensure_structured_logger


class USBCameraController(ModuleRuntime):
    """Multi-camera USB preview + recording using OpenCV."""

    PREVIEW_SIZE = (640, 480)
    UPDATE_INTERVAL = 0.2  # seconds
    MAX_SENSOR_FPS = 120.0
    MAX_NATIVE_SIZE = (1920, 1080)
    NATIVE_ASPECT = MAX_NATIVE_SIZE[1] / MAX_NATIVE_SIZE[0]
    CAPTURE_SLOW_REQUEST_THRESHOLD = 0.35  # seconds

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        self.supervisor = context.supervisor
        self.supervisor_model = context.model
        self.view = context.view
        base_logger = ensure_structured_logger(
            context.logger,
            component="USBCameraController",
            fallback_name=f"{__name__}.USBCameraController",
        )
        self.logger = base_logger.getChild("runtime")
        self.logger.debug("USBCameraController initializing")
        self.display_name = context.display_name
        self.module_dir = context.module_dir

        self.task_manager = BackgroundTaskManager("USBCamerasTasks", self.logger)
        timeout = getattr(self.args, "shutdown_timeout", 15.0)
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=timeout)

        scope_fn = getattr(self.supervisor_model, "preferences_scope", None)
        self.camera_prefs = scope_fn("usb_cameras") if callable(scope_fn) else None

        config_path = getattr(context.model, "config_path", None)
        self.state = USBCameraModel(
            args=self.args,
            module_dir=self.module_dir,
            display_name=self.display_name,
            logger=self.logger,
            config_path=config_path,
            preferences=self.camera_prefs,
        )

        self.view_adapter: Optional[USBCameraViewAdapter] = None
        if self.view is not None:
            self.view_adapter = USBCameraViewAdapter(
                self.view,
                args=self.args,
                preview_size=self.state.PREVIEW_SIZE,
                task_manager=self.task_manager,
                logger=self.logger,
            )

        self.view_manager = USBViewManager(self)
        self.storage_manager = USBStorageManager(self)
        self.discovery = USBCameraDiscovery(self.logger)
        self.device_registry = DeviceRegistry(
            discovery=self.discovery,
            view_adapter=self.view_adapter,
            logger=self.logger,
        )
        self.device_registry.on_selection_changed(self._rebuild_after_selection)
        self.slot_manager = SlotManager(self)
        self.recording_manager = RecordingManager(
            self,
            storage_manager=self.storage_manager,
            logger=self.logger,
        )

        self._stop_event = asyncio.Event()
        self._slots: list = []
        self._storage_fps_counters: dict[int, RollingFpsCounter] = {}
        self._metrics_task: Optional[asyncio.Task] = None
        self._storage_failure_reported = False
        self.preview_stride = 1

        self.save_enabled = bool(self.state.save_enabled)
        self.save_format = self.state.save_format
        self.save_quality = self.state.save_quality
        self.session_retention = self.state.session_retention
        self.min_free_space_mb = self.state.min_free_space_mb
        self.storage_queue_size = self.state.storage_queue_size
        self.save_dir = self.state.save_dir
        self.session_dir = self.state.session_dir
        self.preview_frame_interval = self.state.preview_frame_interval
        self.save_frame_interval = self.state.save_frame_interval
        self.target_fps = self._safe_float(getattr(self.args, "target_fps", None))
        self.overlay_config = dict(getattr(self.state, "overlay_config", {}))
        self.preview_size = (
            self._coerce_dimension(getattr(self.args, "preview_width", None), self.state.PREVIEW_SIZE[0]),
            self._coerce_dimension(getattr(self.args, "preview_height", None), self.state.PREVIEW_SIZE[1]),
        )

        self.logger.debug(
            "Runtime args resolved | preview_size=%s save_enabled=%s save_dir=%s session_dir=%s target_fps=%s",
            self.preview_size,
            self.save_enabled,
            self.save_dir,
            self.session_dir,
            self.target_fps,
        )

        self._storage_hooks = StorageHooks(
            save_enabled=lambda: bool(self.save_enabled),
            session_dir_provider=lambda: self.session_dir,
            frame_to_bgr=lambda frame, fmt, size_hint=None: frame_to_bgr(
                frame,
                fmt,
                size_hint=size_hint,
            ),
            resolve_video_fps=self.resolve_video_fps,
            on_frame_written=self.on_storage_result,
            handle_failure=self.handle_storage_failure,
        )
        self._init_lock = asyncio.Lock()
        self._discovery_task: Optional[asyncio.Task] = None
        self._reconfig_in_progress = False

    # ------------------------------------------------------------------
    # Lifecycle

    async def start(self) -> None:
        if not self.view_adapter:
            self.logger.warning("GUI view unavailable; USB cameras runtime running headless")
        else:
            max_cams = getattr(self.args, "max_cameras", 4)
            self.logger.info(
                "Starting USB Cameras runtime | max_cameras=%s preview_size=%s save_enabled=%s",
                max_cams,
                self.preview_size,
                self.save_enabled,
            )
            self.view_adapter.build_camera_grid(max_cams)
            self.view_adapter.install_io_metrics_panel()
        if self._metrics_task is None:
            self._metrics_task = self.task_manager.create(
                self.view_manager.run_metrics_loop(),
                name="USBCameraPipelineMetrics",
            )

        # Kick off discovery/probing without blocking the UI thread so the window stays resizable.
        if self._discovery_task is None or self._discovery_task.done():
            self._discovery_task = self.task_manager.create(
                self._run_initial_discovery(),
                name="USBCameraInitialDiscovery",
            )

    async def _run_initial_discovery(self) -> None:
        """Perform device search/probing asynchronously so the UI stays responsive."""

        self.view_manager.set_status("Searching for USB cameras…")
        try:
            await self.initialize_cameras()
            await self._await_first_frames(timeout=6.0)
            self.view_manager.refresh_status()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Initial camera discovery failed: %s", exc)
            self.view_manager.set_status("Camera discovery failed")

    async def shutdown(self) -> None:
        await self.shutdown_guard.start()
        self._stop_event.set()

        if self.save_enabled:
            try:
                await asyncio.wait_for(self.storage_manager.disable_saving(), timeout=8.0)
            except asyncio.TimeoutError:
                self.logger.warning("Storage disable during shutdown timed out; forcing shutdown")
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Storage disable during shutdown failed: %s", exc)

        await self.slot_manager.teardown()

        await self.shutdown_guard.cancel()

    async def cleanup(self) -> None:
        return None

    # ------------------------------------------------------------------
    # Discovery + setup helpers

    def _parse_device_indices(self) -> list[int]:
        raw = getattr(self.args, "device_indices", None)
        return self.device_registry.parse_indices(raw)

    def resolve_capture_size(self) -> Optional[tuple[int, int]]:
        width = self._safe_int(getattr(self.args, "capture_width", None))
        height = self._safe_int(getattr(self.args, "capture_height", None))
        if width is None and height is None:
            return None
        if width is None and height is not None:
            width = int(round(height / self.NATIVE_ASPECT))
        if height is None and width is not None:
            height = int(round(width * self.NATIVE_ASPECT))
        if width is None or height is None:
            return None
        width = max(64, int(width))
        height = max(64, int(height))
        return self.state._ensure_even_dimensions(width, height)

    def resolve_save_size(self) -> Optional[tuple[int, int]]:
        width = self._safe_int(getattr(self.args, "save_width", None))
        height = self._safe_int(getattr(self.args, "save_height", None))
        if width is None and height is None:
            return None
        if width is None and height is not None:
            width = int(round(height / self.NATIVE_ASPECT))
        if height is None and width is not None:
            height = int(round(width * self.NATIVE_ASPECT))
        if width is None or height is None:
            return None
        width = max(64, int(width))
        height = max(64, int(height))
        width, height = self.state._ensure_even_dimensions(width, height)
        return self.state.clamp_resolution(width, height, self.MAX_NATIVE_SIZE)

    async def _rebuild_after_selection(self) -> None:
        """Tear down existing slots and re-initialize with the selected devices."""
        if self._reconfig_in_progress:
            return
        if getattr(self.task_manager, "_closing", False):
            return
        if not self.device_registry.discovered_infos and not self._slots:
            return
        self._reconfig_in_progress = True
        try:
            await self.slot_manager.teardown()
            await self.initialize_cameras()
            await self._await_first_frames(timeout=6.0)
        finally:
            self._reconfig_in_progress = False

    async def initialize_cameras(self) -> None:
        async with self._init_lock:
            max_cams = getattr(self.args, "max_cameras", 4)
            requested_indices = self._parse_device_indices()
            discovery_limit = max(32, max_cams * 8)
            infos = self.device_registry.discover_candidates(
                requested=requested_indices,
                max_devices=discovery_limit,
            )
            if not infos:
                self.device_registry.clear()
                self.device_registry.set_discovered_infos([], max_cameras=max_cams)
                self.view_manager.set_status("No USB cameras detected")
                return

            probed_infos = await self.device_registry.probe_devices(infos, limit=max_cams * 4)
            if not probed_infos:
                self.device_registry.clear()
                self.device_registry.set_discovered_infos([], max_cameras=max_cams)
                self.view_manager.set_status("No usable USB cameras found")
                return

            self.device_registry.set_discovered_infos(probed_infos, max_cameras=max_cams)

            capture_size = self.resolve_capture_size()
            save_size = self.resolve_save_size()
            self.logger.info(
                "Initializing USB cameras | requested_indices=%s capture_size=%s save_size=%s target_fps=%s",
                requested_indices,
                capture_size,
                save_size,
                self.target_fps,
            )

            selected_infos = self.device_registry.select_default(max_cameras=max_cams)
            if not selected_infos:
                self.view_manager.set_status("No cameras selected")
                return

            await self.slot_manager.build_slots(
                selected_infos,
                capture_size=capture_size,
                save_size=save_size,
                max_cameras=max_cams,
            )

    async def _await_first_frames(self, timeout: float = 5.0) -> bool:
        if not self._slots:
            return False
        all_ready = True
        for slot in self._slots:
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

    # ------------------------------------------------------------------
    # Command + UI hooks

    async def on_session_dir_available(self, session_dir: Path) -> None:
        self.logger.info("Session directory available: %s", session_dir)
        self.session_dir = session_dir

    async def handle_command(self, command: dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action in {"start_recording", "stop_recording"}:
            directory = (
                command.get("session_dir")
                or command.get("directory")
                or command.get("save_directory")
                or command.get("path")
            )
            if not directory and self.session_dir:
                directory = self.session_dir
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
            if not directory and self.session_dir:
                directory = self.session_dir

            previously_enabled = self.save_enabled
            success = await self.recording_manager.start_recording(
                directory=directory,
                trial_number=command.get("trial_number"),
                trial_label=str(command.get("trial_label") or ""),
            )
            if not success:
                return False
            if not previously_enabled:
                self.logger.info("Frame saving enabled via command without interrupting preview")
            else:
                self.logger.info("Frame saving already active; updated configuration via command")
            return True
        if action == "stop_recording":
            return await self.recording_manager.stop_recording()
        if action:
            self.logger.debug("Unhandled command on USB Cameras: %s", action)
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        if action in {"start_recording", "stop_recording"}:
            self.logger.info(
                "Recording user actions are ignored in the USB cameras stub; use the logger controller."
            )
            return True
        return False

    async def healthcheck(self) -> bool:
        # Keep the runtime considered healthy while running, even if no cameras are present,
        # so the UI window is not torn down during long discovery/probe cycles.
        if self._stop_event.is_set():
            return False
        return True

    # ------------------------------------------------------------------
    # Metrics + telemetry

    def resolve_video_fps(self, slot: USBCameraSlot) -> float:
        if self.target_fps and self.target_fps > 0:
            return float(self.target_fps)
        if slot.storage_pipeline and slot.storage_pipeline.video_fps > 0:
            return float(slot.storage_pipeline.video_fps)
        if slot.capture_fps > 0:
            return float(slot.capture_fps)
        return 30.0

    async def on_storage_result(
        self,
        slot: USBCameraSlot,
        payload: Any,
        result: Any,
        dropped_since_last: int,
    ) -> bool:
        counter = self._storage_fps_counters.get(slot.index)
        if counter is None:
            counter = RollingFpsCounter()
            self._storage_fps_counters[slot.index] = counter
        slot.storage_fps = counter.tick()

        if dropped_since_last:
            self.logger.warning(
                "Storage queue dropped %s frame(s) for camera %s",
                dropped_since_last,
                slot.index,
            )
        return True

    async def handle_storage_failure(self, slot: USBCameraSlot, reason: str) -> None:
        if self._storage_failure_reported:
            return
        self._storage_failure_reported = True
        self.logger.error("Storage failure for camera %s: %s", slot.index, reason)
        await self.storage_manager.disable_saving()

    def record_capture_latency(self, slot: USBCameraSlot, duration: float) -> None:
        if duration > self.CAPTURE_SLOW_REQUEST_THRESHOLD:
            slot.slow_capture_warnings += 1
            if slot.slow_capture_warnings < 5:
                self.logger.warning(
                    "Camera %s capture_request slow: %.3fs",
                    slot.index,
                    duration,
                )

    def log_capture_failure(self, slot: USBCameraSlot, duration: float, exc: Exception) -> None:
        self.logger.warning(
            "Capture failure (camera %s) after %.3fs: %s",
            slot.index,
            duration,
            exc,
        )

    # ------------------------------------------------------------------
    # Helpers

    @property
    def current_trial_number(self) -> int:
        return self.recording_manager.current_trial_number

    @property
    def current_trial_label(self) -> str:
        return self.recording_manager.current_trial_label

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _coerce_dimension(value: Any, default: int) -> int:
        try:
            if value is None:
                return int(default)
            return int(float(value))
        except Exception:
            return int(default)


__all__ = ["USBCameraController"]
