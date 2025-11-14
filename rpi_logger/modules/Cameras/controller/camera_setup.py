"""Camera slot initialization and teardown helpers."""

from __future__ import annotations

import asyncio
from typing import Any, Optional, TYPE_CHECKING

from ..domain.model import CameraModel
from ..domain.pipelines import ImagePipeline
from ..logging_utils import get_module_logger
from .pipeline import PreviewConsumer
from .slot import CameraSlot

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .runtime import CameraController

logger = get_module_logger(__name__)


class CameraSetupManager:
    """Handles camera discovery, slot initialization, and teardown."""

    def __init__(self, controller: "CameraController") -> None:
        self._controller = controller
        logger.debug("CameraSetupManager initialized")

    async def initialize_cameras(self) -> None:
        controller = self._controller
        logger.debug("Initializing cameras | max=%s", getattr(controller.args, "max_cameras", 2))
        picamera_cls = getattr(controller, "picamera_cls", None)
        if picamera_cls is None:
            controller.logger.error("Cannot initialize cameras: picamera class missing")
            return

        try:
            camera_infos = await asyncio.to_thread(picamera_cls.global_camera_info)
        except Exception as exc:
            controller.logger.exception("Failed to enumerate cameras: %s", exc)
            controller.view_manager.set_status("Failed to enumerate cameras")
            return

        if not camera_infos:
            return

        max_cams = getattr(controller.args, "max_cameras", 2)
        saving_active = bool(controller.save_enabled)
        adapter = controller.view_adapter

        for index, info in enumerate(camera_infos[:max_cams]):
            title = controller._state.get_camera_alias(index)
            if adapter is None:
                controller.logger.debug("Skipping preview construction for cam %s (no view)", index)
                continue
            frame, holder, label = adapter.create_preview_slot(index, title)

            camera = None
            try:
                camera = picamera_cls(index)
                self.record_sensor_modes(camera)
                native_size = self.resolve_sensor_resolution(camera)
                capture_size = self.coerce_capture_size(native_size) or native_size or controller.MAX_NATIVE_SIZE
                lores_size = self.compute_lores_size(capture_size)
                sensor_config = None
                if capture_size and self.is_supported_sensor_size(capture_size):
                    bit_depth = controller._sensor_mode_bit_depths.get(tuple(capture_size))
                    if bit_depth:
                        sensor_config = {"output_size": capture_size, "bit_depth": bit_depth}

                config = await asyncio.to_thread(
                    self.build_camera_configuration,
                    camera,
                    capture_size,
                    lores_size,
                    sensor_config,
                )
                await asyncio.to_thread(camera.configure, config)
                await asyncio.to_thread(camera.start)

                actual_config = await asyncio.to_thread(camera.camera_configuration)
                main_block = self.unwrap_config_block(actual_config, "main")
                lores_block = self.unwrap_config_block(actual_config, "lores") if lores_size else None

                main_format = str(main_block.get("format", "")) or "RGB888"
                main_size = self.normalize_size(main_block.get("size")) or capture_size
                if main_size:
                    main_size = self.clamp_resolution(main_size[0], main_size[1], controller.MAX_NATIVE_SIZE)
                    main_size = self.enforce_native_aspect(*main_size)
                preview_default = controller.PREVIEW_SIZE
                stream_label = "main"
                if main_size:
                    controller.logger.info(
                        "Camera %s streaming %sx%s (%s) for preview and recording",
                        index,
                        main_size[0],
                        main_size[1],
                        main_format,
                    )
                else:
                    controller.logger.info(
                        "Camera %s streaming %s for preview and recording",
                        index,
                        stream_label,
                    )

                if lores_size and lores_block is not None:
                    lores_size = self.normalize_size(lores_block.get("size")) or lores_size
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
                slot.capture_main_stream = bool(controller.save_enabled)
                self.update_slot_targets(slot)

                slot.capture_queue = asyncio.Queue()
                slot.preview_queue = asyncio.Queue(maxsize=1)

                slot.preview_gate.configure(controller.preview_frame_interval)
                slot.preview_stride = controller.preview_stride
                controller.storage_manager.configure_storage_gate(slot)
                if controller.view_adapter:
                    controller.view_adapter.bind_preview_resize(
                        slot.frame,
                        lambda width, height, target=slot: controller.view_manager.handle_preview_resize(
                            target,
                            width,
                            height,
                        ),
                    )
                    controller.view_adapter.prime_preview_dimensions(
                        slot.frame,
                        lambda width, height, target=slot: controller.view_manager.handle_preview_resize(
                            target,
                            width,
                            height,
                        ),
                    )

                slot.saving_active = saving_active
                await controller.telemetry.apply_frame_rate(slot)

                pipeline_logger = controller.logger.getChild(f"PipelineCam{index}")
                view_resize_checker = controller.view_adapter.view_is_resizing if controller.view_adapter else None
                slot.image_pipeline = ImagePipeline(
                    camera_index=index,
                    logger=pipeline_logger,
                    view_resize_checker=view_resize_checker,
                    status_refresh=controller.view_manager.refresh_status,
                    fps_window_seconds=2.0,
                    fps_health_checker=controller.telemetry.update_fps_health,
                )

                if saving_active:
                    slot.storage_queue = asyncio.Queue(maxsize=controller.storage_queue_size)
                    slot.storage_queue_size = controller.storage_queue_size
                else:
                    slot.storage_queue = None
                    await controller.storage_manager.stop_storage_resources(slot)

                controller._previews.append(slot)
                controller.view_manager.register_camera_toggle(slot)

                if slot.image_pipeline:
                    slot.capture_task = controller.task_manager.create(
                        slot.image_pipeline.run_capture_loop(
                            slot=slot,
                            camera=camera,
                            stop_event=controller._stop_event,
                            shutdown_queue=controller._shutdown_queue,
                            record_latency=controller.telemetry.record_capture_latency,
                            log_failure=controller.telemetry.log_capture_failure,
                        ),
                        name=f"CameraCapture{index}",
                    )

                    slot.router_task = controller.task_manager.create(
                        slot.image_pipeline.run_frame_router(
                            slot=slot,
                            stop_event=controller._stop_event,
                            shutdown_queue=controller._shutdown_queue,
                            saving_enabled=lambda: bool(controller.save_enabled),
                        ),
                        name=f"CameraFrameRouter{index}",
                    )

                if slot.preview_queue:
                    preview_consumer = PreviewConsumer(
                        stop_event=controller._stop_event,
                        view_adapter=controller.view_adapter,
                        logger=controller.logger.getChild(f"PreviewCam{index}"),
                    )
                    slot.preview_task = controller.task_manager.create(
                        preview_consumer.run(slot),
                        name=f"CameraPreview{index}",
                    )

                if slot.storage_queue:
                    controller.storage_manager.start_storage_consumer(slot)

                if saving_active and slot.storage_queue:
                    await controller.storage_manager.start_storage_resources(slot)
            except Exception as exc:  # pragma: no cover - defensive
                controller.logger.exception("Failed to initialize camera %s: %s", index, exc)
                if camera is not None:
                    try:
                        await asyncio.to_thread(camera.close)
                    except Exception:
                        pass
                controller.view_manager.set_status(f"Camera {index} unavailable")
                continue

        if not controller._previews:
            controller.view_manager.set_status("No cameras initialized")
        else:
            controller.view_manager.refresh_status()

    # ------------------------------------------------------------------
    # Resolution helpers

    def normalize_size(self, value: Any) -> Optional[tuple[int, int]]:
        return CameraModel.normalize_size(value)

    @staticmethod
    def ensure_even_dimensions(width: int, height: int) -> tuple[int, int]:
        return CameraModel._ensure_even_dimensions(width, height)

    def clamp_resolution(
        self,
        width: int,
        height: int,
        native: Optional[tuple[int, int]],
    ) -> tuple[int, int]:
        return self._controller.state.clamp_resolution(width, height, native)

    def enforce_native_aspect(self, width: int, height: int) -> tuple[int, int]:
        return self._controller.state.enforce_native_aspect(width, height)

    def compute_lores_size(self, main_size: tuple[int, int]) -> Optional[tuple[int, int]]:
        if not main_size:
            return None
        controller = self._controller
        main_width, main_height = main_size
        preview_width, preview_height = controller.PREVIEW_SIZE
        if preview_width >= main_width or preview_height >= main_height:
            return None
        target_width = min(preview_width, main_width)
        target_height = min(preview_height, main_height)
        if target_width < 160 or target_height < 120:
            return None
        target_width, target_height = self.ensure_even_dimensions(target_width, target_height)
        return (target_width, target_height)

    def coerce_capture_size(self, native_size: Optional[tuple[int, int]]) -> Optional[tuple[int, int]]:
        target = self.get_requested_resolution()
        if target is None:
            return native_size
        width, height = target
        if width <= 0 or height <= 0:
            return native_size
        return self.ensure_even_dimensions(width, height)

    def coerce_save_size(self, capture_size: Optional[tuple[int, int]]) -> Optional[tuple[int, int]]:
        controller = self._controller
        width_value = getattr(controller.args, "save_width", None)
        height_value = getattr(controller.args, "save_height", None)
        width = CameraModel._safe_int(width_value)
        height = CameraModel._safe_int(height_value)
        if width is None and height is None:
            return capture_size
        capture = self.normalize_size(capture_size) or controller.MAX_NATIVE_SIZE
        if width is not None and height is not None:
            width, height = self.enforce_native_aspect(width, height)
            return self.clamp_resolution(width, height, capture)
        if width is not None and capture:
            height = int(round(width * controller.NATIVE_ASPECT))
            width, height = self.enforce_native_aspect(width, height)
            return self.clamp_resolution(width, height, capture)
        if height is not None and capture:
            width = int(round(height / controller.NATIVE_ASPECT))
            width, height = self.enforce_native_aspect(width, height)
            return self.clamp_resolution(width, height, capture)
        return capture

    def update_slot_targets(self, slot: CameraSlot) -> None:
        controller = self._controller
        slot.save_size = self.coerce_save_size(slot.main_size) or slot.main_size or controller.MAX_NATIVE_SIZE

    def get_requested_resolution(self) -> Optional[tuple[int, int]]:
        controller = self._controller
        width = CameraModel._safe_int(getattr(controller.args, "save_width", None))
        height = CameraModel._safe_int(getattr(controller.args, "save_height", None))
        if width is None and height is None:
            return None
        if width is None and height is not None:
            width = int(round(height / controller.NATIVE_ASPECT))
        if height is None and width is not None:
            height = int(round(width * controller.NATIVE_ASPECT))
        if width is None or height is None:
            return None
        width = max(64, int(width))
        height = max(64, int(height))
        return self.ensure_even_dimensions(width, height)

    def record_sensor_modes(self, camera: Any) -> None:
        controller = self._controller
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
        if not controller._sensor_mode_sizes:
            controller._sensor_mode_sizes = sizes
            controller._sensor_mode_bit_depths = entries
        else:
            controller._sensor_mode_sizes &= sizes
            controller._sensor_mode_bit_depths = {
                size: entries.get(size, controller._sensor_mode_bit_depths.get(size, 0))
                for size in controller._sensor_mode_sizes
            }

        if not controller._sensor_mode_sizes:
            return

        sorted_sizes = sorted(f"{w}x{h}" for w, h in controller._sensor_mode_sizes)
        controller.logger.info(
            "Intersected sensor modes (%d): %s",
            len(controller._sensor_mode_sizes),
            ", ".join(sorted_sizes),
        )

    def is_supported_sensor_size(self, size: Optional[tuple[int, int]]) -> bool:
        controller = self._controller
        if size is None or not controller._sensor_mode_sizes:
            return True
        return tuple(size) in controller._sensor_mode_sizes

    def get_requested_resolution(self) -> Optional[tuple[int, int]]:
        controller = self._controller
        width = CameraModel._safe_int(getattr(controller.args, "save_width", None))
        height = CameraModel._safe_int(getattr(controller.args, "save_height", None))
        if width is None and height is None:
            return None
        if width is None and height is not None:
            width = int(round(height / controller.NATIVE_ASPECT))
        if height is None and width is not None:
            height = int(round(width * controller.NATIVE_ASPECT))
        if width is None or height is None:
            return None
        width = max(64, int(width))
        height = max(64, int(height))
        return self.ensure_even_dimensions(width, height)

    def record_sensor_modes(self, camera: Any) -> None:
        controller = self._controller
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
        if not controller._sensor_mode_sizes:
            controller._sensor_mode_sizes = sizes
            controller._sensor_mode_bit_depths = entries
        else:
            controller._sensor_mode_sizes &= sizes
            controller._sensor_mode_bit_depths = {
                size: entries.get(size, controller._sensor_mode_bit_depths.get(size, 0))
                for size in controller._sensor_mode_sizes
            }
        if not controller._sensor_mode_sizes:
            return
        sorted_sizes = sorted(f"{w}x{h}" for w, h in controller._sensor_mode_sizes)
        controller.logger.info(
            "Intersected sensor modes (%d): %s",
            len(controller._sensor_mode_sizes),
            ", ".join(sorted_sizes),
        )

    def is_supported_sensor_size(self, size: Optional[tuple[int, int]]) -> bool:
        controller = self._controller
        if size is None or not controller._sensor_mode_sizes:
            return True
        return tuple(size) in controller._sensor_mode_sizes

    def resolve_sensor_resolution(self, camera: Any) -> Optional[tuple[int, int]]:
        size = self.normalize_size(getattr(camera, "sensor_resolution", None))
        if size:
            return self.clamp_resolution(size[0], size[1], self._controller.MAX_NATIVE_SIZE)
        properties = getattr(camera, "camera_properties", None)
        if isinstance(properties, dict):
            size = self.normalize_size(properties.get("PixelArraySize"))
            if size:
                return self.clamp_resolution(size[0], size[1], self._controller.MAX_NATIVE_SIZE)
        return self._controller.MAX_NATIVE_SIZE

    def unwrap_config_block(self, config: Any, key: str) -> dict[str, Any]:
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

    def build_camera_configuration(
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
            if lores_size:
                kwargs["lores"] = {"size": lores_size, "format": "YUV420"}
            main_config["format"] = "RGB888"
            return camera.create_video_configuration(**kwargs)

    async def teardown_slot(self, slot: CameraSlot) -> None:
        controller = self._controller
        controller._shutdown_queue(slot.capture_queue)
        controller._shutdown_queue(slot.preview_queue)
        controller._shutdown_queue(slot.storage_queue)

        camera_obj = slot.camera
        if camera_obj:
            try:
                await asyncio.to_thread(camera_obj.stop)
            except Exception as exc:  # pragma: no cover - defensive
                controller.logger.debug("Error stopping camera %s: %s", slot.index, exc)

        tasks = [slot.capture_task, slot.router_task, slot.preview_task, slot.storage_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()

        for task in tasks:
            if not task:
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                controller.logger.debug("Error awaiting task for camera %s: %s", slot.index, exc)

        slot.capture_task = None
        slot.router_task = None
        slot.preview_task = None
        slot.storage_task = None

        if slot.image_pipeline:
            slot.image_pipeline.reset_metrics(slot)
            slot.image_pipeline = None

        await controller.storage_manager.stop_storage_resources(slot)

        if camera_obj:
            try:
                await asyncio.to_thread(camera_obj.close)
            except Exception as exc:  # pragma: no cover - defensive
                controller.logger.debug("Error closing camera %s: %s", slot.index, exc)
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

    async def reinitialize_cameras(self) -> None:
        controller = self._controller
        existing = list(controller._previews)
        if existing:
            controller.logger.info("Reconfiguring %d camera(s)", len(existing))
        else:
            controller.logger.info("Reconfiguring cameras (none active)")

        for slot in existing:
            try:
                await self.teardown_slot(slot)
            except Exception as exc:  # pragma: no cover - defensive
                controller.logger.debug("Error tearing down camera %s: %s", slot.index, exc)

        controller._previews.clear()

        await self.initialize_cameras()
        controller.view_manager.refresh_status()
