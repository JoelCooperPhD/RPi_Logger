"""Cameras runtime built on the stub (codex) VMC stack."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional


try:
    from picamera2 import Picamera2  # type: ignore
except Exception:  # pragma: no cover - dependency optional on dev hosts
    Picamera2 = None  # type: ignore

from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard

from ..constants import FRAME_LOG_COUNT

from ..model import CameraModel, CapturedFrame, FrameGate, FramePayload
from ..model.image_pipeline import ImagePipeline
from ..view import CameraViewAdapter
from ..frame_timing import FrameTimingTracker
from ..storage import CameraStoragePipeline, StorageWriteResult
from ..utils import frame_to_image as convert_frame_to_image
from .pipeline import PreviewConsumer, StorageConsumer, StorageHooks
from .slot import CameraSlot


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
        base_logger = context.logger
        self.logger = base_logger.getChild("CamerasRuntime") if base_logger else logging.getLogger("CamerasRuntime")
        self.display_name = context.display_name
        self.module_dir = context.module_dir

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

        self._stop_event = asyncio.Event()
        self._previews: List[CameraSlot] = []
        self._storage_hooks = StorageHooks(
            save_enabled=lambda: bool(self.save_enabled),
            session_dir_provider=lambda: self.session_dir,
            save_stills_enabled=lambda: bool(self.save_stills_enabled),
            frame_to_image=lambda frame, fmt, size_hint=None: convert_frame_to_image(
                frame,
                fmt,
                size_hint=size_hint,
            ),
            resolve_video_fps=self._resolve_video_fps,
            on_frame_written=self._on_storage_result,
            handle_failure=self._handle_storage_failure,
        )
        self._sensor_mode_sizes: set[tuple[int, int]] = set()
        self._sensor_mode_bit_depths: dict[tuple[int, int], int] = {}
        self._metrics_task: Optional[asyncio.Task] = None
        self._saved_count = 0
        self._storage_failure_reported = False
        self._sensor_sync_pending = False
        self.preview_fraction = self._clamp_preview_fraction(
            getattr(self.args, "preview_fraction", getattr(self._state, "preview_fraction", 1.0))
        )
        setattr(self.args, "preview_fraction", self.preview_fraction)
        self.preview_stride = self._fraction_to_stride(self.preview_fraction)
        self._apply_preview_fraction()

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
        self._install_view_hooks()
        self._sync_record_toggle()

        if self.view_adapter and self._metrics_task is None:
            self._metrics_task = self.task_manager.create(
                self._run_metrics_loop(),
                name="CameraPipelineMetrics",
            )

        if Picamera2 is None:
            self.logger.error("Cannot initialize cameras: picamera2 missing")
            return

        await self._initialize_cameras()
        await self._flush_sensor_sync()
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
            previously_enabled = self.save_enabled
            success = await self._enable_saving(directory)
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
            await self._disable_saving()
            self.logger.info("Frame saving disabled via command")
            return True
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        if action == "update_preview_settings":
            await self._update_preview_settings(kwargs)
            return True
        if action == "update_record_settings":
            await self._update_record_settings(kwargs)
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

    def _set_status(self, message: str, *, level: int = logging.INFO) -> None:
        self.state.update_status(message, level=level)

    def _install_view_hooks(self) -> None:
        if not self.view_adapter:
            return
        self.view_adapter.install_preview_fps_menu(
            getter=lambda: self.preview_fraction,
            handler=self._handle_preview_fraction_selection,
        )

    def _register_camera_toggle(self, slot: CameraSlot) -> None:
        if not self.view_adapter:
            return
        self.view_adapter.register_camera_toggle(
            index=slot.index,
            title=slot.title,
            enabled=slot.preview_enabled,
            handler=self._handle_camera_toggle_request,
        )

    async def _handle_camera_toggle_request(self, index: int, enabled: bool) -> None:
        slot = self._slot_by_index(index)
        if slot is None or slot.preview_enabled == enabled:
            return
        slot.preview_enabled = enabled
        if enabled:
            slot.preview_gate.configure(slot.preview_gate.period)
            if self.view_adapter:
                self.view_adapter.show_camera_waiting(slot)
        else:
            if self.view_adapter:
                self.view_adapter.show_camera_hidden(slot)
        self._refresh_status()
        self._refresh_preview_layout()

    def _slot_by_index(self, index: int) -> Optional[CameraSlot]:
        for slot in self._previews:
            if slot.index == index:
                return slot
        return None

    def _refresh_preview_layout(self) -> None:
        if self.view_adapter:
            self.view_adapter.refresh_preview_layout(self._previews)

    def _refresh_status(self) -> None:
        """Summarize current camera/save state for diagnostics/UI."""
        active_cameras = sum(1 for slot in self._previews if slot.camera is not None)
        if active_cameras == 0:
            message = "No cameras detected"
            if self.save_enabled:
                if self.save_dir:
                    message += f" | saving enabled -> {self.save_dir}"
                else:
                    message += " | saving enabled"
        else:
            suffix = "s" if active_cameras != 1 else ""
            message = f"{active_cameras} camera{suffix} active"
            if self.save_enabled:
                target_dir = self.save_dir or self.session_dir
                if target_dir:
                    message += f" | saving to {target_dir}"
                else:
                    message += " | saving enabled"
                if self.session_dir:
                    message += f" | session {self.session_dir.name}"
            else:
                if self.capture_preferences_enabled:
                    message += " | saving disabled (awaiting logger start)"
                else:
                    message += " | saving disabled"

        metrics = self._compute_stage_fps()
        stage_summary = self._format_stage_status(metrics)
        if stage_summary:
            message += f" | {stage_summary}"

        logical = self._get_requested_resolution()
        if logical:
            message += f" | logical res={logical[0]}x{logical[1]} (software)"

        if self.save_enabled:
            drop_total = sum(slot.storage_drop_total for slot in self._previews)
            if drop_total:
                message += f" | queue drops {drop_total}"
            if not self.save_stills_enabled:
                message += " | stills=off"
            fps_values = [slot.last_video_fps for slot in self._previews if slot.last_video_fps > 0]
            if fps_values:
                avg_fps = sum(fps_values) / len(fps_values)
                message += f" | fps≈{avg_fps:.1f}"

        self._set_status(message)
        self._publish_pipeline_metrics()

    def _compute_stage_fps(self) -> dict[str, float]:
        stage_keys = ("capture_fps", "process_fps", "preview_fps", "storage_fps")
        metrics = {key: 0.0 for key in stage_keys}
        active_slots = [slot for slot in self._previews if slot.camera is not None]
        if not active_slots:
            return metrics

        for key in stage_keys:
            values = [getattr(slot, key, 0.0) for slot in active_slots if getattr(slot, key, 0.0) > 0.0]
            metrics[key] = sum(values) / len(values) if values else 0.0
        return metrics

    def _format_stage_status(self, metrics: dict[str, float]) -> str:
        capture_avg = metrics.get("capture_fps", 0.0)
        process_avg = metrics.get("process_fps", 0.0)
        preview_avg = metrics.get("preview_fps", 0.0)
        storage_avg = metrics.get("storage_fps", 0.0)

        if capture_avg or process_avg or preview_avg or storage_avg:
            return (
                f"stage fps cap={capture_avg:.1f}"
                f"/proc={process_avg:.1f}"
                f"/disp={preview_avg:.1f}"
                f"/save={storage_avg:.1f}"
            )
        return ""

    def _publish_pipeline_metrics(self) -> None:
        if not self.view_adapter:
            return
        metrics = self._compute_stage_fps()
        self.view_adapter.update_pipeline_metrics(
            capture_fps=metrics.get("capture_fps", 0.0),
            process_fps=metrics.get("process_fps", 0.0),
            preview_fps=metrics.get("preview_fps", 0.0),
            storage_fps=metrics.get("storage_fps", 0.0),
        )

    async def _run_metrics_loop(self) -> None:
        while not self._stop_event.is_set():
            self._publish_pipeline_metrics()
            await asyncio.sleep(self.UPDATE_INTERVAL)
        self._publish_pipeline_metrics()

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

    def _sync_record_toggle(self) -> None:
        if not self.view_adapter:
            return
        desired = bool(self.save_enabled or self.capture_preferences_enabled)
        self.view_adapter.sync_record_toggle(
            desired,
            capture_disabled=self.save_enabled,
        )

    def _emit_frame_telemetry(
        self,
        slot: CameraPreview,
        payload: FramePayload,
        *,
        image_path: Optional[Path],
        video_written: bool,
        queue_drops: int = 0,
        video_fps: float = 0.0,
    ) -> None:
        sensor_ts = payload.sensor_timestamp_ns
        if sensor_ts is not None:
            sensor_part = f"sensor={sensor_ts}ns"
        else:
            sensor_part = f"ts={payload.timestamp:.3f}s"

        drops = payload.dropped_since_last
        drop_part = f"drops={drops}" if drops is not None else "drops=0"
        video_part = "video=Y" if video_written else "video=N"

        image_part = ""
        if image_path is not None:
            image_part = f"img={image_path.name}"

        components = [
            f"Cam{slot.index} frame {payload.capture_index}",
            sensor_part,
            drop_part,
            video_part,
        ]
        if image_part:
            components.append(image_part)
        if queue_drops:
            components.append(f"qdrop={queue_drops}")
        if video_fps > 0:
            components.append(f"fps={video_fps:.2f}")

        entry = " | ".join(components)
        self.logger.debug("Storage telemetry -> %s", entry)

    def _handle_preview_resize(self, slot: CameraSlot, width: int, height: int) -> None:
        new_size = (width, height)
        if new_size == slot.size:
            return
        slot.size = new_size

    def _refresh_preview_fps_ui(self) -> None:
        if self.view_adapter:
            self.view_adapter.refresh_preview_fps_ui()

    def _record_sensor_modes(self, camera: Any) -> None:
        if not camera:
            return
        try:
            modes = getattr(camera, "sensor_modes", None)
        except Exception:  # pragma: no cover - defensive
            modes = None
        if not modes:
            return

        entries: dict[tuple[int, int], int] = {}
        for mode in modes:
            if not isinstance(mode, dict):
                continue
            size = mode.get("size")
            if not size:
                continue
            bit_depth = mode.get("bit_depth")
            if isinstance(size, tuple) and len(size) == 2:
                entries[(int(size[0]), int(size[1]))] = int(bit_depth) if isinstance(bit_depth, (int, float)) else 0

        if not entries:
            return

        sizes = set(entries.keys())
        if not self._sensor_mode_sizes:
            self._sensor_mode_sizes = sizes
            self._sensor_mode_bit_depths = entries
        else:
            self._sensor_mode_sizes &= sizes
            self._sensor_mode_bit_depths = {
                size: entries.get(size, self._sensor_mode_bit_depths.get(size, 0))
                for size in self._sensor_mode_sizes
            }

        if not self._sensor_mode_sizes:
            return

        sorted_sizes = sorted(f"{w}x{h}" for w, h in self._sensor_mode_sizes)
        self.logger.info(
            "Intersected sensor modes (%d): %s",
            len(self._sensor_mode_sizes),
            ", ".join(sorted_sizes),
        )

    def _is_supported_sensor_size(self, size: Optional[tuple[int, int]]) -> bool:
        if size is None:
            return True
        if not self._sensor_mode_sizes:
            return True
        return tuple(size) in self._sensor_mode_sizes

    def _get_requested_resolution(self) -> Optional[tuple[int, int]]:
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
        width, height = self._ensure_even_dimensions(width, height)
        return width, height

    def _apply_preview_fraction(self) -> None:
        base_interval = self.save_frame_interval if self.save_frame_interval > 0 else (1.0 / self.MAX_SENSOR_FPS)
        fraction = self.preview_fraction if self.preview_fraction > 0 else 1.0
        interval = base_interval / fraction
        self.preview_frame_interval = interval
        self.preview_stride = self._fraction_to_stride(self.preview_fraction)
        for slot in self._previews:
            slot.preview_gate.configure(interval)
            slot.preview_stride = self.preview_stride
            self._configure_storage_gate(slot)
        if hasattr(self._state, "preview_fraction"):
            self._state.preview_fraction = self.preview_fraction
        if hasattr(self.args, "preview_fps"):
            if self.save_frame_interval > 0:
                capture_fps = 1.0 / self.save_frame_interval
                setattr(self.args, "preview_fps", round(capture_fps * self.preview_fraction, 3))
            else:
                setattr(self.args, "preview_fps", None)
        self._refresh_preview_fps_ui()
        self._request_sensor_sync()

    async def _handle_preview_fraction_selection(self, fraction_value: Optional[float]) -> None:
        await self._update_preview_settings({"fraction": fraction_value})

    def _configure_storage_gate(self, slot: CameraSlot) -> None:
        interval = self.save_frame_interval if self.save_frame_interval > 0 else 0.0
        slot.frame_rate_gate.configure(interval)

    # ------------------------------------------------------------------
    # Camera initialization & preview loops

    async def _initialize_cameras(self) -> None:
        assert Picamera2 is not None

        try:
            camera_infos = await asyncio.to_thread(Picamera2.global_camera_info)
        except Exception as exc:
            self.logger.exception("Failed to enumerate cameras: %s", exc)
            self._set_status("Failed to enumerate cameras")
            return

        if not camera_infos:
            return

        max_cams = getattr(self.args, "max_cameras", 2)
        saving_active = bool(self.save_enabled)

        adapter = self.view_adapter

        for index, info in enumerate(camera_infos[:max_cams]):
            title = self._state.get_camera_alias(index)
            if adapter is None:
                self.logger.debug("Skipping preview construction for cam %s (no view)", index)
                continue
            frame, holder, label = adapter.create_preview_slot(index, title)

            camera = None
            try:
                camera = Picamera2(index)
                self._record_sensor_modes(camera)
                native_size = self._resolve_sensor_resolution(camera)
                capture_size = self._coerce_capture_size(native_size) or native_size or self.MAX_NATIVE_SIZE
                lores_size = self._compute_lores_size(capture_size)
                sensor_config = None
                if capture_size and self._is_supported_sensor_size(capture_size):
                    bit_depth = self._sensor_mode_bit_depths.get(tuple(capture_size))
                    if bit_depth:
                        sensor_config = {"output_size": capture_size, "bit_depth": bit_depth}

                config = await asyncio.to_thread(
                    self._build_camera_configuration,
                    camera,
                    capture_size,
                    lores_size,
                    sensor_config,
                )
                await asyncio.to_thread(camera.configure, config)
                await asyncio.to_thread(camera.start)

                actual_config = await asyncio.to_thread(camera.camera_configuration)
                main_block = self._unwrap_config_block(actual_config, "main")
                lores_block = self._unwrap_config_block(actual_config, "lores") if lores_size else None

                main_format = str(main_block.get("format", "")) or "RGB888"
                main_size = self._normalize_size(main_block.get("size")) or capture_size
                if main_size:
                    main_size = self._clamp_resolution(main_size[0], main_size[1], self.MAX_NATIVE_SIZE)
                    main_size = self._enforce_native_aspect(*main_size)
                preview_default = self.PREVIEW_SIZE
                stream_label = "main"
                if main_size:
                    self.logger.info(
                        "Camera %s streaming %sx%s (%s) for preview and recording",
                        index,
                        main_size[0],
                        main_size[1],
                        main_format,
                    )
                else:
                    self.logger.info(
                        "Camera %s streaming %s for preview and recording",
                        index,
                        stream_label,
                    )

                if lores_size and lores_block is not None:
                    lores_size = self._normalize_size(lores_block.get("size")) or lores_size
                    preview_stream = "lores"
                    preview_format = str(lores_block.get("format", "")) or main_format
                else:
                    preview_stream = "main"
                    preview_format = main_format
                preview_native_size = lores_size if preview_stream == "lores" else main_size
                slot = CameraSlot(
                    index=index,
                    camera=camera,
                    frame=frame,
                    holder=holder,
                    label=label,
                    size=preview_default,
                    title=title,
                    main_format=main_format,
                    preview_format=preview_format,
                    main_size=main_size,
                    preview_stream=preview_stream,
                    main_stream="main",
                    preview_stream_size=preview_native_size,
                    save_size=None,
                )
                slot.capture_main_stream = bool(self.save_enabled)
                self._update_slot_targets(slot)

                slot.capture_queue = asyncio.Queue()
                slot.preview_queue = asyncio.Queue(maxsize=1)

                slot.preview_gate.configure(self.preview_frame_interval)
                slot.preview_stride = self.preview_stride
                self._configure_storage_gate(slot)
                if self.view_adapter:
                    self.view_adapter.bind_preview_resize(
                        slot.frame,
                        lambda width, height, target=slot: self._handle_preview_resize(target, width, height),
                    )
                    self.view_adapter.prime_preview_dimensions(
                        slot.frame,
                        lambda width, height, target=slot: self._handle_preview_resize(target, width, height),
                    )

                slot.saving_active = saving_active
                await self._apply_frame_rate(slot)

                pipeline_logger = self.logger.getChild(f"PipelineCam{index}")
                view_resize_checker = self.view_adapter.view_is_resizing if self.view_adapter else None
                slot.image_pipeline = ImagePipeline(
                    camera_index=index,
                    logger=pipeline_logger,
                    view_resize_checker=view_resize_checker,
                    status_refresh=self._refresh_status,
                    fps_window_seconds=2.0,
                )

                if saving_active:
                    slot.storage_queue = asyncio.Queue(maxsize=self.storage_queue_size)
                    slot.storage_queue_size = self.storage_queue_size
                    await self._start_storage_resources(slot)
                else:
                    slot.storage_queue = None
                    await self._stop_storage_resources(slot)

                self._previews.append(slot)
                self._register_camera_toggle(slot)

                if slot.image_pipeline:
                    slot.capture_task = self.task_manager.create(
                        slot.image_pipeline.run_capture_loop(
                            slot=slot,
                            camera=camera,
                            stop_event=self._stop_event,
                            shutdown_queue=self._shutdown_queue,
                            record_latency=self._record_capture_latency,
                            log_failure=self._log_capture_failure,
                        ),
                        name=f"CameraCapture{index}",
                    )

                    slot.router_task = self.task_manager.create(
                        slot.image_pipeline.run_frame_router(
                            slot=slot,
                            stop_event=self._stop_event,
                            shutdown_queue=self._shutdown_queue,
                            saving_enabled=lambda: bool(self.save_enabled),
                        ),
                        name=f"CameraFrameRouter{index}",
                    )

                if slot.preview_queue:
                    preview_consumer = PreviewConsumer(
                        stop_event=self._stop_event,
                        view_adapter=self.view_adapter,
                        logger=self.logger.getChild(f"PreviewCam{index}"),
                    )
                    slot.preview_task = self.task_manager.create(
                        preview_consumer.run(slot),
                        name=f"CameraPreview{index}",
                    )

                if slot.storage_queue:
                    self._start_storage_consumer(slot)

            except Exception as exc:
                self.logger.exception("Failed to start preview for camera %s: %s", index, exc)
                self._set_status(f"Camera {index} unavailable")
                label.configure(text="Camera unavailable", fg="#ff5555")
                if camera is not None:
                    try:
                        await asyncio.to_thread(camera.stop)
                        await asyncio.to_thread(camera.close)
                    except Exception:
                        pass

        if not self._previews:
            self._set_status("No cameras initialized")
        else:
            self._refresh_status()

    async def _apply_frame_rate(self, slot: CameraSlot) -> None:
        camera = slot.camera
        if not camera:
            return

        target_interval = self._current_sensor_interval()

        if target_interval is None:
            if slot.frame_duration_us is not None:
                default_us = max(3333, int(1_000_000 / self.MAX_SENSOR_FPS))
                try:
                    await asyncio.to_thread(
                        camera.set_controls,
                        {"FrameDurationLimits": (default_us, default_us)},
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.debug("FrameDuration reset failed for cam %s: %s", slot.index, exc)
                slot.frame_duration_us = None
            return

        frame_us = max(3333, int(target_interval * 1_000_000))
        if slot.frame_duration_us == frame_us:
            return

        try:
            await asyncio.to_thread(
                camera.set_controls,
                {"FrameDurationLimits": (frame_us, frame_us)},
            )
            slot.frame_duration_us = frame_us
            self.logger.info(
                "Camera %s sensor frame duration set to %.2f ms",
                slot.index,
                frame_us / 1000.0,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.debug("Unable to set frame duration for cam %s: %s", slot.index, exc)

    def _current_sensor_interval(self) -> Optional[float]:
        interval = self.save_frame_interval
        if interval and interval > 0:
            return interval
        # Keep the sensor free-running when recording is uncapped, letting the
        # driver choose the fastest allowed cadence instead of inheriting any
        # preview throttling. Preview FPS controls already drop frames via the
        # FrameGate, so constraining the sensor would only reduce headroom.
        return None

    async def _sync_sensor_frame_rates(self) -> None:
        for slot in self._previews:
            try:
                await self._apply_frame_rate(slot)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Frame rate sync failed for cam %s: %s", slot.index, exc)

    async def _flush_sensor_sync(self) -> None:
        if not self._sensor_sync_pending:
            return
        self._sensor_sync_pending = False
        await self._sync_sensor_frame_rates()

    def _request_sensor_sync(self) -> None:
        if self._stop_event.is_set():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self._sensor_sync_pending = True
            return
        self.task_manager.create(
            self._sync_sensor_frame_rates(),
            name="CameraSensorSync",
        )
        self._sensor_sync_pending = False

    async def _teardown_slot(self, slot: CameraSlot) -> None:
        self._shutdown_queue(slot.capture_queue)
        self._shutdown_queue(slot.preview_queue)
        self._shutdown_queue(slot.storage_queue)

        camera_obj = slot.camera
        if camera_obj:
            try:
                await asyncio.to_thread(camera_obj.stop)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Error stopping camera %s: %s", slot.index, exc)

        tasks = [slot.capture_task, slot.router_task, slot.preview_task, slot.storage_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()

        for task in tasks:
            if not task:
                continue
            try:
                await task
            except asyncio.CancelledError:  # cooperative cancellation
                pass
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Error awaiting task for camera %s: %s", slot.index, exc)

        slot.capture_task = None
        slot.router_task = None
        slot.preview_task = None
        slot.storage_task = None

        if slot.image_pipeline:
            slot.image_pipeline.reset_metrics(slot)
            slot.image_pipeline = None

        await self._stop_storage_resources(slot)

        if camera_obj:
            try:
                await asyncio.to_thread(camera_obj.close)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Error closing camera %s: %s", slot.index, exc)
        slot.camera = None
        slot.capture_queue = None
        slot.preview_queue = None
        slot.storage_queue = None
        slot.was_resizing = False
        slot.capture_index = 0
        slot.timing_tracker.reset()
        slot.last_hardware_fps = 0.0
        slot.last_expected_interval_ns = None
        slot.storage_drop_since_last = 0
        slot.storage_drop_total = 0
        slot.last_video_frame_count = 0
        slot.video_stall_frames = 0
        slot.last_video_fps = 0.0
        slot.session_camera_dir = None
        slot.slow_capture_warnings = 0

        if slot.frame and slot.frame.winfo_exists():
            slot.frame.destroy()

    async def _reinitialize_cameras(self) -> None:
        existing = list(self._previews)
        if existing:
            self.logger.info("Reconfiguring %d camera(s)", len(existing))
        else:
            self.logger.info("Reconfiguring cameras (none active)")

        for slot in existing:
            try:
                await self._teardown_slot(slot)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Error tearing down camera %s: %s", slot.index, exc)

        self._previews.clear()

        await self._initialize_cameras()
        self._refresh_status()

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

    def _log_capture_failure(self, slot: CameraSlot, elapsed: float, exc: Exception) -> None:
        slot.slow_capture_warnings += 1
        if slot.slow_capture_warnings <= 5 or slot.slow_capture_warnings % 25 == 0:
            self.logger.warning(
                "Capture loop error (camera %s) after %.3fs (saving=%s, queue=%s): %s",
                slot.index,
                elapsed,
                self.save_enabled,
                slot.storage_queue_size,
                exc,
            )

    def _record_capture_latency(self, slot: CameraSlot, elapsed: float) -> None:
        if elapsed > self.CAPTURE_SLOW_REQUEST_THRESHOLD:
            slot.slow_capture_warnings += 1
            if slot.slow_capture_warnings <= 5 or slot.slow_capture_warnings % 25 == 0:
                session_name = self.session_dir.name if self.session_dir else "n/a"
                self.logger.warning(
                    "Camera %s capture_request slow: %.3fs (saving=%s, session=%s)",
                    slot.index,
                    elapsed,
                    self.save_enabled,
                    session_name,
                )
        elif slot.slow_capture_warnings and elapsed < self.CAPTURE_SLOW_REQUEST_THRESHOLD / 2:
            slot.slow_capture_warnings = 0

    def _update_storage_metrics(self, slot: CameraSlot, result: StorageWriteResult) -> bool:
        pipeline = slot.storage_pipeline
        if pipeline is not None:
            slot.last_video_frame_count = pipeline.video_frame_count
        slot.last_video_fps = result.video_fps
        if result.video_written:
            slot.video_stall_frames = 0
            return False
        slot.video_stall_frames += 1
        return slot.video_stall_frames >= self.VIDEO_STALL_THRESHOLD

    async def _on_storage_result(
        self,
        slot: CameraSlot,
        payload: FramePayload,
        storage_result: StorageWriteResult,
        queue_drops: int,
    ) -> bool:
        image_path = storage_result.image_path
        if image_path is not None:
            self._saved_count += 1
            if self._saved_count <= 3 or self._saved_count % 25 == 0:
                self.logger.info(
                    "Camera %s stored still %d -> %s (total saved %d)",
                    slot.index,
                    payload.capture_index,
                    image_path,
                    self._saved_count,
                )

        pipeline = slot.storage_pipeline
        if pipeline is not None:
            pipeline.log_frame(payload, queue_drops=queue_drops)

        self._emit_frame_telemetry(
            slot,
            payload,
            image_path=image_path,
            video_written=storage_result.video_written,
            queue_drops=queue_drops,
            video_fps=storage_result.video_fps,
        )

        stalled = self._update_storage_metrics(slot, storage_result)
        if stalled:
            await self._handle_storage_failure(slot, "video writer stalled")
            return False
        return True

    async def _handle_storage_failure(self, slot: CameraSlot, reason: str) -> None:
        if self._storage_failure_reported:
            return
        self._storage_failure_reported = True
        self.logger.error(
            "Storage failure on camera %s: %s (video_frames=%d, queue_drops=%d)",
            slot.index,
            reason,
            slot.last_video_frame_count,
            slot.storage_drop_total,
        )
        self._set_status(f"Recording stopped: {reason}", level=logging.ERROR)
        await self._disable_saving()
        await self._reinitialize_cameras()

    async def _update_preview_settings(self, settings: dict[str, Any]) -> None:
        changed = False
        fraction_raw = settings.get("fraction")
        fps = settings.get("fps")
        interval = settings.get("interval")

        fraction_value = self._safe_float(fraction_raw)
        if fraction_value is not None and fraction_value > 0:
            new_fraction = self._clamp_preview_fraction(fraction_value)
            if abs(new_fraction - self.preview_fraction) > 1e-3:
                self.preview_fraction = new_fraction
                setattr(self.args, "preview_fraction", new_fraction)
                self._apply_preview_fraction()
                changed = True
        elif fps is not None or interval is not None:
            absolute_interval = self._derive_interval(fps=fps, interval=interval)
            if absolute_interval > 0 and self.save_frame_interval > 0:
                desired_fraction = self.save_frame_interval / absolute_interval
                new_fraction = self._clamp_preview_fraction(desired_fraction)
                if abs(new_fraction - self.preview_fraction) > 1e-3:
                    self.preview_fraction = new_fraction
                    setattr(self.args, "preview_fraction", new_fraction)
                    self._apply_preview_fraction()
                    changed = True
            else:
                self.logger.info("Preview FPS adjustments require a configured recording FPS; ignoring request")
        if any(key in settings for key in ("size", "resolution")):
            self.logger.info("Preview resolution controls are disabled; ignoring request")

        if changed:
            await self.state.persist_module_preferences()

    async def _update_record_settings(self, settings: dict[str, Any]) -> None:
        enabled = settings.get("enabled")
        directory = settings.get("directory")
        size = settings.get("size")
        fps = settings.get("fps")
        interval = settings.get("interval")
        fmt = settings.get("format")
        quality = settings.get("quality")

        if enabled is not None:
            requested = bool(enabled)
            if self.save_enabled and not requested:
                self.logger.info(
                    "Capture menu disable ignored; recording is controlled by the logger."
                )
                self.capture_preferences_enabled = True
            else:
                self.capture_preferences_enabled = requested
                if requested and not self.save_enabled:
                    self.logger.info(
                        "Capture menu enabled for configuration. Recording will start when triggered by the logger."
                    )
            self._sync_record_toggle()

        if directory:
            if hasattr(self.args, "save_dir"):
                setattr(self.args, "save_dir", directory)
            await self._update_save_directory(directory)

        if fmt:
            fmt_lower = str(fmt).lower()
            if fmt_lower in {"jpeg", "jpg", "png", "webp"}:
                self.save_format = fmt_lower
                if hasattr(self.args, "save_format"):
                    setattr(self.args, "save_format", fmt_lower)
                self.logger.info("Save format set to %s", self.save_format)

        if quality is not None:
            q_val = self._safe_int(quality)
            if q_val is not None:
                self.save_quality = max(1, min(q_val, 100))
                if hasattr(self.args, "save_quality"):
                    setattr(self.args, "save_quality", self.save_quality)
                self.logger.info("Save quality set to %d", self.save_quality)

        if fps is not None or interval is not None:
            new_interval = self._derive_interval(fps=fps, interval=interval)
            if new_interval != self.save_frame_interval:
                self.save_frame_interval = new_interval
                if hasattr(self.args, "save_fps"):
                    if new_interval <= 0.0:
                        setattr(self.args, "save_fps", None)
                    else:
                        setattr(self.args, "save_fps", round(1.0 / new_interval, 3))
                if new_interval <= 0.0:
                    self.logger.info("Recording FPS uncapped")
                else:
                    self.logger.info("Recording FPS limited to %.2f (interval %.3fs)", 1.0 / new_interval, new_interval)
                self._apply_preview_fraction()
                await self._sync_sensor_frame_rates()

        if size is not None:
            native_selected = isinstance(size, str) and size.lower() == "native"
            normalized_size: Optional[tuple[int, int]] = None
            if not native_selected:
                normalized_size = self._normalize_size(size)
                if normalized_size is None:
                    self.logger.warning("Invalid recording resolution selection: %s", size)
                else:
                    self._set_logical_resolution(normalized_size)
                    self._apply_save_resolution_choice(normalized_size, native_selected=False)
            else:
                self._set_logical_resolution(None)
                self._apply_save_resolution_choice(None, native_selected=True)

        await self.state.persist_module_preferences()
        self._refresh_status()

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

        if size is not None and not self._is_supported_sensor_size(size):
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
            self._set_status("Resolution unchanged: sensor only exposes native mode")
            return False

        if prev_width == new_width and prev_height == new_height:
            self.logger.debug("Capture resolution already %s; skipping reconfigure", label)
            return False

        setattr(self.args, "capture_width", new_width)
        setattr(self.args, "capture_height", new_height)

        self.logger.info("Capture resolution set to %s; reinitializing cameras", label)
        await self._reinitialize_cameras()
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
        await self._reinitialize_cameras()
        await self._await_first_frames(timeout=6.0)
        return False

    def _apply_save_resolution_choice(
        self,
        size: Optional[tuple[int, int]],
        *,
        native_selected: bool,
    ) -> None:
        if native_selected:
            self.logger.info("Preview/save resolution set to native stream size (software)")
        elif size is not None:
            self.logger.info(
                "Preview/save resolution set to %sx%s (software scaling)",
                size[0],
                size[1],
            )

        for slot in self._previews:
            self._update_slot_targets(slot)

    def _set_logical_resolution(self, size: Optional[tuple[int, int]]) -> None:
        if size is None:
            setattr(self.args, "save_width", None)
            setattr(self.args, "save_height", None)
            return

        width, height = size
        setattr(self.args, "save_width", int(width))
        setattr(self.args, "save_height", int(height))

    def _update_slot_targets(self, slot: CameraSlot) -> None:
        slot.save_size = self._coerce_save_size(slot.main_size) or slot.main_size or self.MAX_NATIVE_SIZE

    def _derive_interval(self, *, fps: Any = None, interval: Any = None) -> float:
        if fps is not None:
            try:
                fps_val = float(fps)
            except (TypeError, ValueError):
                fps_val = 0.0
            if fps_val <= 0.0:
                return 0.0
            fps_val = min(fps_val, self.MAX_SENSOR_FPS)
            return 1.0 / fps_val
        if interval is not None:
            try:
                interval_val = float(interval)
            except (TypeError, ValueError):
                interval_val = 0.0
            if interval_val <= 0.0:
                return 0.0
            interval_val = max(interval_val, 1.0 / self.MAX_SENSOR_FPS)
            return interval_val
        return 0.0

    async def _start_storage_resources(self, slot: CameraSlot) -> None:
        if not self.session_dir:
            self.logger.error("Cannot start storage for camera %s: session directory unavailable", slot.index)
            return

        if slot.storage_pipeline is not None:
            await slot.storage_pipeline.stop()

        try:
            camera_dir = await asyncio.to_thread(self._ensure_camera_dir_sync, slot.index, self.session_dir)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Cannot prepare per-camera directory for cam %s: %s", slot.index, exc)
            return
        slot.session_camera_dir = camera_dir

        camera_alias = slot.title or self.state.get_camera_alias(slot.index)
        camera_slug = self.state.get_camera_alias_slug(slot.index)

        pipeline = CameraStoragePipeline(
            slot.index,
            camera_dir,
            camera_alias=camera_alias,
            camera_slug=camera_slug,
            main_size=slot.main_size,
            save_format=self.save_format,
            save_quality=self.save_quality,
            max_fps=self.MAX_SENSOR_FPS,
            overlay_config=dict(self.overlay_config),
            save_stills=self.save_stills_enabled,
            camera=slot.camera,
            logger=self.logger.getChild(f"StorageCam{slot.index}"),
        )
        await pipeline.start()
        fps_hint = self._resolve_video_fps(slot)
        await pipeline.start_video_recording(fps_hint)
        slot.storage_pipeline = pipeline
        self.logger.info(
            "Storage ready for %s -> dir=%s | queue=%d",
            camera_alias,
            camera_dir,
            slot.storage_queue_size,
        )

    def _start_storage_consumer(self, slot: CameraSlot) -> None:
        if slot.storage_queue is None or slot.storage_task is not None:
            return

        storage_consumer = StorageConsumer(
            stop_event=self._stop_event,
            hooks=self._storage_hooks,
            logger=self.logger.getChild(f"StorageCam{slot.index}"),
        )
        slot.storage_task = self.task_manager.create(
            storage_consumer.run(slot),
            name=f"CameraStorage{slot.index}",
        )

    async def _stop_storage_resources(self, slot: CameraSlot) -> None:
        pipeline = slot.storage_pipeline
        slot.storage_pipeline = None
        if pipeline is None:
            return

        await pipeline.stop()

    async def _activate_storage_for_all_slots(self) -> None:
        for slot in self._previews:
            slot.saving_active = True
            slot.capture_main_stream = True
            if slot.storage_queue is None:
                slot.storage_queue = asyncio.Queue(maxsize=self.storage_queue_size)
                slot.storage_queue_size = self.storage_queue_size
            self._start_storage_consumer(slot)
            await self._start_storage_resources(slot)

    async def _deactivate_storage_for_all_slots(self) -> None:
        shutdown_tasks: list[asyncio.Task] = []
        pending_slots: list[CameraSlot] = []

        for slot in self._previews:
            slot.saving_active = False
            slot.capture_main_stream = False
            queue = slot.storage_queue
            if queue is not None:
                self._shutdown_queue(queue)
            if slot.storage_task is not None:
                shutdown_tasks.append(slot.storage_task)
            pending_slots.append(slot)

        if shutdown_tasks:
            await asyncio.gather(*shutdown_tasks, return_exceptions=True)

        for slot in pending_slots:
            await self._stop_storage_resources(slot)
            slot.storage_queue = None
            slot.storage_task = None

    def _resolve_video_fps(self, slot: CameraSlot) -> float:
        if slot.last_hardware_fps and slot.last_hardware_fps > 0:
            return min(float(slot.last_hardware_fps), self.MAX_SENSOR_FPS)
        if slot.last_expected_interval_ns and slot.last_expected_interval_ns > 0:
            fps = 1_000_000_000.0 / float(slot.last_expected_interval_ns)
            if fps > 0:
                return min(fps, self.MAX_SENSOR_FPS)
        if self.save_frame_interval > 0:
            fps = 1.0 / self.save_frame_interval
            return min(max(fps, 1.0), self.MAX_SENSOR_FPS)
        return 30.0

    async def _enable_saving(self, directory: Optional[Any]) -> bool:
        external_session = False
        session_dir: Optional[Path] = None
        base_dir: Optional[Path] = None

        if directory:
            try:
                session_dir = Path(directory)
            except Exception:
                self.logger.error("Invalid session directory: %s", directory)
                return False
            try:
                await asyncio.to_thread(session_dir.mkdir, parents=True, exist_ok=True)
            except Exception as exc:
                self.logger.error("Unable to prepare session directory %s: %s", session_dir, exc)
                return False
            external_session = True
        else:
            target_dir = self.save_dir or self._resolve_save_dir()
            try:
                base_dir = Path(target_dir)
            except Exception:
                self.logger.error("Invalid save directory: %s", target_dir)
                return False
            session_dir = await asyncio.to_thread(self._prepare_session_directory_sync, base_dir)
            if session_dir is None:
                return False

        if session_dir is None:
            self.logger.error("Recording session directory unavailable")
            return False

        if not external_session:
            self.save_dir = base_dir
        self.session_dir = session_dir
        self.save_enabled = True
        self.capture_preferences_enabled = True
        self._storage_failure_reported = False
        self._saved_count = 0
        await self._activate_storage_for_all_slots()
        self._request_sensor_sync()
        self._sync_record_toggle()
        self._refresh_status()
        rate_desc = (
            "uncapped"
            if self.save_frame_interval <= 0
            else f"{1.0 / self.save_frame_interval:.2f} fps"
        )
        base_display = str(session_dir) if external_session else str(self.save_dir)
        self.logger.info(
            "Recording enabled -> base=%s | session=%s | rate=%s | queue=%d | stills=%s",
            base_display,
            self.session_dir,
            rate_desc,
            self.storage_queue_size,
            "on" if self.save_stills_enabled else "off",
        )
        return True

    async def _disable_saving(self) -> None:
        if not self.save_enabled:
            return
        total_drops = sum(slot.storage_drop_total for slot in self._previews)
        saved_frames = self._saved_count
        await self._deactivate_storage_for_all_slots()
        self.save_enabled = False
        self.capture_preferences_enabled = False
        self.session_dir = None
        self._storage_failure_reported = False
        self._request_sensor_sync()
        self._sync_record_toggle()
        self._refresh_status()
        self.logger.info(
            "Recording disabled (saved %d frames, drops=%d)",
            saved_frames,
            total_drops,
        )

    async def _update_save_directory(self, directory: Any) -> None:
        try:
            path = Path(directory)
        except Exception:
            self.logger.error("Invalid save directory: %s", directory)
            return

        if self.save_dir and self.save_dir == path:
            return

        try:
            await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
        except Exception as exc:
            self.logger.error("Unable to prepare save directory %s: %s", path, exc)
            return

        self.save_dir = path
        self.logger.info("Save directory set to %s", path)

        if self.save_enabled:
            session_dir = await asyncio.to_thread(self._prepare_session_directory_sync, path)
            if session_dir is None:
                self.logger.error("Unable to refresh session directory after path change; leaving previous session active")
                return
            self.session_dir = session_dir
            for slot in self._previews:
                await self._start_storage_resources(slot)

    def _unwrap_config_block(self, config: Any, key: str) -> dict[str, Any]:
        try:
            if isinstance(config, dict):
                raw = config.get(key, {}) or {}
            else:
                raw = getattr(config, key, None)
        except Exception:  # pragma: no cover - defensive
            return {}

        if isinstance(raw, dict):
            return raw

        block: dict[str, Any] = {}
        if raw is None:
            return block

        for attr in ("format", "size", "stride", "framesize"):
            value = getattr(raw, attr, None)
            if value is not None:
                block[attr] = value
        return block

    def _resolve_sensor_resolution(self, camera: Any) -> Optional[tuple[int, int]]:
        size = self._normalize_size(getattr(camera, "sensor_resolution", None))
        if size:
            return self._clamp_resolution(size[0], size[1], self.MAX_NATIVE_SIZE)

        properties = getattr(camera, "camera_properties", None)
        if isinstance(properties, dict):
            size = self._normalize_size(properties.get("PixelArraySize"))
            if size:
                return self._clamp_resolution(size[0], size[1], self.MAX_NATIVE_SIZE)
        return self.MAX_NATIVE_SIZE

    def _coerce_capture_size(self, native_size: Optional[tuple[int, int]]) -> Optional[tuple[int, int]]:
        width_value = getattr(self.args, "capture_width", None)
        height_value = getattr(self.args, "capture_height", None)

        width = self._safe_int(width_value)
        height = self._safe_int(height_value)

        target = self._get_requested_resolution()
        if target is None:
            return native_size

        width, height = target
        if width <= 0 or height <= 0:
            return native_size
        return self._ensure_even_dimensions(width, height)

    def _coerce_save_size(self, capture_size: Optional[tuple[int, int]]) -> Optional[tuple[int, int]]:
        width_value = getattr(self.args, "save_width", None)
        height_value = getattr(self.args, "save_height", None)

        width = self._safe_int(width_value)
        height = self._safe_int(height_value)

        if width is None and height is None:
            return capture_size

        capture = self._normalize_size(capture_size) or self.MAX_NATIVE_SIZE

        if width is not None and height is not None:
            width, height = self._enforce_native_aspect(width, height)
            return self._clamp_resolution(width, height, capture)

        if width is not None and capture:
            height = int(round(width * self.NATIVE_ASPECT))
            width, height = self._enforce_native_aspect(width, height)
            return self._clamp_resolution(width, height, capture)

        if height is not None and capture:
            width = int(round(height / self.NATIVE_ASPECT))
            width, height = self._enforce_native_aspect(width, height)
            return self._clamp_resolution(width, height, capture)

        return capture

    def _resolve_save_dir(self) -> Path:
        return self.state.resolve_save_dir()

    def _prepare_session_directory_sync(self, base_dir: Path) -> Optional[Path]:
        return self.state.prepare_session_directory_sync(base_dir)

    def _ensure_camera_dir_sync(self, camera_index: int, session_dir: Path) -> Path:
        return self.state.ensure_camera_dir_sync(camera_index, session_dir)

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        return CameraModel._safe_int(value)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        return CameraModel._safe_float(value)

    @staticmethod
    def _clamp_preview_fraction(value: float) -> float:
        choices = CameraController.PREVIEW_FRACTION_CHOICES
        value = max(min(value, choices[0]), choices[-1])
        return min(choices, key=lambda choice: abs(choice - value))

    @staticmethod
    def _fraction_to_stride(fraction: float) -> int:
        fraction = CameraController._clamp_preview_fraction(fraction)
        mapping = {1.0: 1, 0.5: 2, 1 / 3: 3, 0.25: 4}
        return mapping.get(fraction, 1)

    def _compute_lores_size(self, main_size: tuple[int, int]) -> Optional[tuple[int, int]]:
        """Compute lores stream size that is <= main size and suitable for preview."""
        if not main_size:
            return None

        main_width, main_height = main_size
        preview_width, preview_height = self.PREVIEW_SIZE

        if preview_width >= main_width or preview_height >= main_height:
            return None

        target_width = min(preview_width, main_width)
        target_height = min(preview_height, main_height)

        if target_width < 160 or target_height < 120:
            return None

        target_width, target_height = self._ensure_even_dimensions(target_width, target_height)
        return (target_width, target_height)

    def _clamp_resolution(self, width: int, height: int, native: Optional[tuple[int, int]]) -> tuple[int, int]:
        return self.state.clamp_resolution(width, height, native)

    def _enforce_native_aspect(self, width: int, height: int) -> tuple[int, int]:
        return self.state.enforce_native_aspect(width, height)

    @staticmethod
    def _ensure_even_dimensions(width: int, height: int) -> tuple[int, int]:
        return CameraModel._ensure_even_dimensions(width, height)

    @staticmethod
    def _normalize_size(value: Any) -> Optional[tuple[int, int]]:
        return CameraModel.normalize_size(value)

    def _build_camera_configuration(
        self,
        camera,
        capture_size: tuple[int, int],
        lores_size: Optional[tuple[int, int]],
        sensor_config: Optional[dict],
    ):
        main_config = {"size": capture_size, "format": "YUV420"}
        kwargs: dict[str, Any] = {
            "main": main_config,
            "sensor": sensor_config,
            "encode": "main",
        }

        lores_format = "XRGB8888"
        if lores_size:
            kwargs["lores"] = {"size": lores_size, "format": lores_format}
            kwargs["display"] = "lores"
        else:
            kwargs["display"] = "main"

        try:
            return camera.create_video_configuration(**kwargs)
        except Exception:
            # Fallback for platforms that do not support RGB lores streams
            if lores_size:
                kwargs["lores"] = {"size": lores_size, "format": "YUV420"}
            main_config["format"] = "RGB888"
            return camera.create_video_configuration(**kwargs)

__all__ = ["CameraController"]
