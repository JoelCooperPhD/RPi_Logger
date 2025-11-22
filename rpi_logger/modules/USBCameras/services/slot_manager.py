"""Slot creation and teardown helpers for the USB cameras controller."""

from __future__ import annotations

import asyncio
from typing import Iterable, Optional

from vmc.runtime_helpers import BackgroundTaskManager

from rpi_logger.core.logging_utils import ensure_structured_logger
from rpi_logger.modules.USBCameras.domain.pipelines import USBCapturePipeline
from rpi_logger.modules.USBCameras.io.capture import USBCamera
from rpi_logger.modules.USBCameras.pipeline import PreviewConsumer
from rpi_logger.modules.USBCameras.controller.slot import USBCameraSlot


class SlotManager:
    """Builds, owns, and tears down per-camera slots."""

    def __init__(self, controller) -> None:
        self.controller = controller
        self.logger = ensure_structured_logger(
            controller.logger,
            component="SlotManager",
            fallback_name=f"{__name__}.SlotManager",
        )

    @property
    def slots(self):
        return self.controller._slots

    # ------------------------------------------------------------------
    # Lifecycle

    async def teardown(self) -> None:
        controller = self.controller
        controller._stop_event.set()

        try:
            await controller.storage_manager.deactivate_storage_for_all_slots()
        except Exception:  # pragma: no cover - defensive
            pass

        for slot in controller._slots:
            self._shutdown_queue(getattr(slot, "capture_queue", None))
            self._shutdown_queue(getattr(slot, "preview_queue", None))
            self._shutdown_queue(getattr(slot, "storage_queue", None))

        await controller.task_manager.shutdown()

        for slot in list(controller._slots):
            camera = getattr(slot, "camera", None)
            if not camera:
                continue
            try:
                await asyncio.to_thread(camera.stop)
            except Exception:  # pragma: no cover - defensive
                pass

        controller._slots.clear()

        controller._stop_event = asyncio.Event()
        controller.task_manager = BackgroundTaskManager("USBCamerasTasks", controller.logger)
        if controller.view_adapter:
            controller.view_adapter.task_manager = controller.task_manager
        controller._metrics_task = None
        controller._discovery_task = None

    async def build_slots(
        self,
        infos: Iterable,
        *,
        capture_size: Optional[tuple[int, int]],
        save_size: Optional[tuple[int, int]],
        max_cameras: int,
    ) -> None:
        controller = self.controller
        adapter = controller.view_adapter

        for cam_idx, info in enumerate(infos):
            if cam_idx >= max_cameras:
                break

            frame = holder = label = None
            if adapter is not None:
                title = controller.state.get_camera_alias(cam_idx)
                frame, holder, label = adapter.create_preview_slot(cam_idx, title)
            else:
                title = controller.state.get_camera_alias(cam_idx)

            camera = USBCamera(
                info,
                target_size=capture_size,
                target_fps=controller.target_fps,
                backend=None,
                logger=self.logger,
            )
            started = await asyncio.to_thread(camera.start)
            if not started:
                self.logger.error("Failed to initialize USB camera %s", info.index)
                continue

            main_size = capture_size or camera.info.native_size or controller.MAX_NATIVE_SIZE
            self.logger.info(
                "Camera %s streaming | main_size=%s preview_size=%s saving=%s",
                cam_idx,
                main_size,
                controller.preview_size,
                controller.save_enabled,
            )

            slot = USBCameraSlot(
                index=cam_idx,
                camera=camera,
                frame=frame,
                holder=holder,
                label=label,
                size=controller.preview_size,
                title=title,
                main_format="RGB888",
                preview_format="RGB888",
                main_size=main_size,
                preview_stream="main",
                main_stream="main",
                preview_stream_size=main_size,
                save_size=save_size or main_size,
            )
            slot.capture_main_stream = True

            slot.capture_queue = asyncio.Queue()
            slot.preview_queue = asyncio.Queue(maxsize=1)
            if controller.save_enabled:
                slot.storage_queue = asyncio.Queue(maxsize=controller.storage_queue_size)
                slot.storage_queue_size = controller.storage_queue_size
            else:
                slot.storage_queue = None

            slot.preview_gate.configure(controller.preview_frame_interval)
            slot.preview_stride = controller.preview_stride
            controller.storage_manager.configure_storage_gate(slot)

            if adapter:
                adapter.bind_preview_resize(
                    slot.frame,
                    lambda width, height, target=slot: controller.view_manager.handle_preview_resize(  # type: ignore[arg-type]
                        target,
                        width,
                        height,
                    ),
                )
                adapter.prime_preview_dimensions(
                    slot.frame,
                    lambda width, height, target=slot: controller.view_manager.handle_preview_resize(  # type: ignore[arg-type]
                        target,
                        width,
                        height,
                    ),
                )

            slot.saving_active = bool(controller.save_enabled)

            pipeline_logger = self.logger.getChild(f"PipelineCam{slot.index}")
            view_resize_checker = adapter.view_is_resizing if adapter else None
            slot.image_pipeline = USBCapturePipeline(
                camera_index=slot.index,
                logger=pipeline_logger,
                view_resize_checker=view_resize_checker,
                status_refresh=controller.view_manager.refresh_status,
                fps_window_seconds=2.0,
            )

            controller._slots.append(slot)

            if slot.image_pipeline:
                slot.capture_task = controller.task_manager.create(
                    slot.image_pipeline.run_capture_loop(
                        slot=slot,
                        camera=camera,
                        stop_event=controller._stop_event,
                        shutdown_queue=self._shutdown_queue,
                        record_latency=controller.record_capture_latency,
                        log_failure=controller.log_capture_failure,
                    ),
                    name=f"USBCameraCapture{slot.index}",
                )

                slot.router_task = controller.task_manager.create(
                    slot.image_pipeline.run_frame_router(
                        slot=slot,
                        stop_event=controller._stop_event,
                        shutdown_queue=self._shutdown_queue,
                        saving_enabled=lambda: bool(controller.save_enabled and slot.saving_active),
                    ),
                    name=f"USBCameraFrameRouter{slot.index}",
                )

            if slot.preview_queue and adapter:
                preview_consumer = PreviewConsumer(
                    stop_event=controller._stop_event,
                    view_adapter=adapter,
                    logger=self.logger.getChild(f"PreviewCam{slot.index}"),
                )
                slot.preview_task = controller.task_manager.create(
                    preview_consumer.run(slot),
                    name=f"USBCameraPreview{slot.index}",
                )

            if slot.storage_queue and controller.save_enabled:
                controller.storage_manager.start_storage_consumer(slot)
                await controller.storage_manager.start_storage_resources(slot)

        if not controller._slots:
            controller.view_manager.set_status("No cameras initialized")
        else:
            controller.view_manager.refresh_status()

    # ------------------------------------------------------------------
    # Helpers

    @staticmethod
    def _shutdown_queue(queue: Optional[asyncio.Queue]) -> None:
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


__all__ = ["SlotManager"]
