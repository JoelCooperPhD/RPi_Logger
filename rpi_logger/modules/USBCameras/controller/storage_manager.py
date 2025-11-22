"""Storage helpers extracted from the USB Cameras controller."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from ..io.storage import CameraStoragePipeline
from ..pipeline import StorageConsumer

if TYPE_CHECKING:  # pragma: no cover - typing only helpers
    from .runtime import USBCameraController
    from .slot import USBCameraSlot


class USBStorageManager:
    """Encapsulates recording/session lifecycle management."""

    def __init__(self, controller: "USBCameraController") -> None:
        self._controller = controller
        self.logger = controller.logger.getChild("storage")
        self.logger.debug("USBStorageManager initialized")

    # ------------------------------------------------------------------
    # Per-slot helpers

    def configure_storage_gate(self, slot: "USBCameraSlot") -> None:
        controller = self._controller
        interval = controller.save_frame_interval if controller.save_frame_interval > 0 else 0.0
        slot.frame_rate_gate.configure(interval)
        self.logger.debug(
            "Configured storage gate | cam=%s interval=%.3f", slot.index, interval
        )

    async def start_storage_resources(self, slot: "USBCameraSlot") -> None:
        controller = self._controller
        session_dir = controller.session_dir
        if not session_dir:
            self.logger.error(
                "Cannot start storage for camera %s: session directory unavailable",
                slot.index,
            )
            return

        if slot.storage_pipeline is not None:
            await slot.storage_pipeline.stop()

        try:
            camera_dir = await asyncio.to_thread(
                controller.state.ensure_camera_dir_sync,
                slot.index,
                session_dir,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error(
                "Cannot prepare per-camera directory for cam %s: %s",
                slot.index,
                exc,
            )
            return
        slot.session_camera_dir = camera_dir

        camera_alias = slot.title or controller.state.get_camera_alias(slot.index)
        camera_slug = controller.state.get_camera_alias_slug(slot.index)

        pipeline = CameraStoragePipeline(
            slot.index,
            camera_dir,
            camera_alias=camera_alias,
            camera_slug=camera_slug,
            main_size=slot.main_size,
            save_format=controller.save_format,
            save_quality=controller.save_quality,
            max_fps=controller.target_fps or controller.MAX_SENSOR_FPS,
            overlay_config=dict(controller.overlay_config),
            camera=None,
            logger=self.logger.getChild(f"cam{slot.index}"),
        )
        pipeline.set_trial_context(
            controller.current_trial_number,
            controller.current_trial_label,
        )
        await pipeline.start()
        fps_hint = controller.resolve_video_fps(slot)
        await pipeline.start_video_recording(fps_hint)
        slot.storage_pipeline = pipeline
        self.logger.info(
            "Storage ready for %s -> dir=%s | queue=%d | trial=%s",
            camera_alias,
            camera_dir,
            slot.storage_queue_size,
            controller.current_trial_number,
        )

    def start_storage_consumer(self, slot: "USBCameraSlot") -> None:
        controller = self._controller
        if slot.storage_queue is None or slot.storage_task is not None:
            return

        storage_consumer = StorageConsumer(
            stop_event=controller._stop_event,
            hooks=controller._storage_hooks,
            logger=self.logger.getChild(f"cam{slot.index}"),
        )
        slot.storage_task = controller.task_manager.create(
            storage_consumer.run(slot),
            name=f"USBCameraStorage{slot.index}",
        )

    async def stop_storage_resources(self, slot: "USBCameraSlot") -> None:
        pipeline = slot.storage_pipeline
        slot.storage_pipeline = None
        if pipeline is None:
            return
        await pipeline.stop()

    # ------------------------------------------------------------------
    # Bulk activation helpers

    async def activate_storage_for_all_slots(self) -> None:
        controller = self._controller
        for slot in controller._slots:
            slot.saving_active = True
            slot.capture_main_stream = True
            if slot.storage_queue is None:
                slot.storage_queue = asyncio.Queue(maxsize=controller.storage_queue_size)
                slot.storage_queue_size = controller.storage_queue_size
            self.start_storage_consumer(slot)
            await self.start_storage_resources(slot)

    async def deactivate_storage_for_all_slots(self) -> None:
        controller = self._controller
        shutdown_tasks: list[asyncio.Task] = []
        pending_slots: list["USBCameraSlot"] = []

        for slot in controller._slots:
            slot.saving_active = False
            slot.capture_main_stream = False
            queue = slot.storage_queue
            if queue is not None:
                controller._shutdown_queue(queue)
            if slot.storage_task is not None:
                shutdown_tasks.append(slot.storage_task)
            pending_slots.append(slot)

        if shutdown_tasks:
            await asyncio.gather(*shutdown_tasks, return_exceptions=True)

        for slot in pending_slots:
            await self.stop_storage_resources(slot)
            slot.storage_queue = None
            slot.storage_task = None

    # ------------------------------------------------------------------
    # Recording lifecycle

    async def enable_saving(self, directory: Optional[Path | str]) -> bool:
        controller = self._controller
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
            target_dir = controller.save_dir or controller.state.resolve_save_dir()
            try:
                base_dir = Path(target_dir)
            except Exception:
                self.logger.error("Invalid save directory: %s", target_dir)
                return False
            session_dir = await asyncio.to_thread(controller.state.prepare_session_directory_sync, base_dir)
            if session_dir is None:
                return False

        if session_dir is None:
            return False

        controller.session_dir = session_dir
        controller.save_dir = base_dir or session_dir

        await self.activate_storage_for_all_slots()
        controller.save_enabled = True
        controller.state.save_enabled = True
        controller.state.capture_preferences_enabled = True
        location = session_dir if external_session else controller.save_dir
        self.logger.info(
            "Frame saving enabled -> %s (retention=%s)",
            location,
            controller.session_retention,
        )
        return True

    async def disable_saving(self) -> bool:
        controller = self._controller
        await self.deactivate_storage_for_all_slots()
        controller.save_enabled = False
        controller.state.save_enabled = False
        controller.state.capture_preferences_enabled = False
        self.logger.info("Frame saving disabled")
        return True


__all__ = ["USBStorageManager"]
