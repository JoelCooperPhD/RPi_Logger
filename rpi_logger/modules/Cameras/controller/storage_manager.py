"""Storage helpers extracted from CameraController."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from ..io.storage import CameraStoragePipeline
from .pipeline import StorageConsumer

if TYPE_CHECKING:  # pragma: no cover - typing only helpers
    from .runtime import CameraController
    from .slot import CameraSlot


class CameraStorageManager:
    """Encapsulates recording/session lifecycle management."""

    def __init__(self, controller: "CameraController") -> None:
        self._controller = controller
        self.logger = controller.logger.getChild("storage")
        self.logger.debug("CameraStorageManager initialized")

    # ------------------------------------------------------------------
    # Per-slot helpers

    def configure_storage_gate(self, slot: "CameraSlot") -> None:
        controller = self._controller
        interval = controller.save_frame_interval if controller.save_frame_interval > 0 else 0.0
        slot.frame_rate_gate.configure(interval)

    async def start_storage_resources(self, slot: "CameraSlot") -> None:
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

        camera_handle = None if slot.force_software_encoder else slot.camera
        if slot.force_software_encoder:
            self.logger.warning(
                "Camera %s using software encoding due to frame-rate constraints",
                slot.index,
            )
        pipeline = CameraStoragePipeline(
            slot.index,
            camera_dir,
            camera_alias=camera_alias,
            camera_slug=camera_slug,
            main_size=slot.main_size,
            save_format=controller.save_format,
            save_quality=controller.save_quality,
            max_fps=controller.MAX_SENSOR_FPS,
            overlay_config=dict(controller.overlay_config),
            camera=camera_handle,
            logger=self.logger.getChild(f"cam{slot.index}"),
        )
        pipeline.set_trial_context(
            controller.current_trial_number,
            controller.current_trial_label,
        )
        await pipeline.start()
        observed_fps = await controller.telemetry.await_slot_fps(slot)
        if observed_fps <= 0:
            observed_fps = controller.telemetry.resolve_video_fps(slot)
        fps_hint = observed_fps if pipeline.uses_hardware_encoder else None
        await pipeline.start_video_recording(fps_hint)
        slot.storage_pipeline = pipeline
        self.logger.info(
            "Storage ready for %s -> dir=%s | queue=%d | trial=%s",
            camera_alias,
            camera_dir,
            slot.storage_queue_size,
            controller.current_trial_number,
        )

    def start_storage_consumer(self, slot: "CameraSlot") -> None:
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
            name=f"CameraStorage{slot.index}",
        )

    async def stop_storage_resources(self, slot: "CameraSlot") -> None:
        pipeline = slot.storage_pipeline
        slot.storage_pipeline = None
        if pipeline is None:
            return
        await pipeline.stop()

    # ------------------------------------------------------------------
    # Bulk activation helpers

    async def activate_storage_for_all_slots(self) -> None:
        controller = self._controller
        for slot in controller._previews:
            if controller.save_frame_interval > 0:
                fps_sample = await controller.telemetry.await_slot_fps(slot, timeout=1.0)
                if not controller.telemetry.enforce_target_fps(slot, observed=fps_sample):
                    alias = controller.state.get_camera_alias(slot.index)
                    raise RuntimeError(
                        f"{alias} cannot match the requested recording FPS. Reduce the target or wait for the sensor."
                    )
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
        pending_slots: list["CameraSlot"] = []

        for slot in controller._previews:
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

    async def enable_saving(self, directory: Optional[Any]) -> bool:
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
            self.logger.error("Recording session directory unavailable")
            return False

        if not external_session:
            controller.save_dir = base_dir
        controller.session_dir = session_dir
        controller.save_enabled = True
        controller.capture_preferences_enabled = True
        controller._storage_failure_reported = False
        controller._saved_count = 0
        try:
            await self.activate_storage_for_all_slots()
        except RuntimeError as exc:
            self.logger.error("Unable to enable recording: %s", exc)
            await self.deactivate_storage_for_all_slots()
            controller.save_enabled = False
            controller.capture_preferences_enabled = False
            controller.session_dir = None
            controller.view_manager.set_status(str(exc), level=logging.ERROR)
            return False

        controller.telemetry.request_sensor_sync()
        controller.view_manager.sync_record_toggle()
        controller.view_manager.refresh_status()
        rate_desc = (
            "uncapped"
            if controller.save_frame_interval <= 0
            else f"{1.0 / controller.save_frame_interval:.2f} fps"
        )
        base_display = str(session_dir) if external_session else str(controller.save_dir)
        self.logger.info(
            "Recording enabled -> base=%s | session=%s | rate=%s | queue=%d | stills=%s",
            base_display,
            controller.session_dir,
            rate_desc,
            controller.storage_queue_size,
            "on" if controller.save_stills_enabled else "off",
        )
        return True

    async def disable_saving(self) -> None:
        controller = self._controller
        if not controller.save_enabled:
            return
        total_drops = sum(slot.storage_drop_total for slot in controller._previews)
        saved_frames = controller._saved_count
        await self.deactivate_storage_for_all_slots()
        controller.save_enabled = False
        controller.capture_preferences_enabled = False
        controller.session_dir = None
        controller._storage_failure_reported = False
        controller.telemetry.request_sensor_sync()
        controller.view_manager.sync_record_toggle()
        controller.view_manager.refresh_status()
        self.logger.info(
            "Recording disabled (saved %d frames, drops=%d)",
            saved_frames,
            total_drops,
        )

    async def update_save_directory(self, directory: Any) -> None:
        controller = self._controller
        try:
            path = Path(directory)
        except Exception:
            self.logger.error("Invalid save directory: %s", directory)
            return

        if controller.save_dir and controller.save_dir == path:
            return

        try:
            await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
        except Exception as exc:
            self.logger.error("Unable to prepare save directory %s: %s", path, exc)
            return

        controller.save_dir = path
        self.logger.info("Save directory set to %s", path)

        if controller.save_enabled:
            session_dir = await asyncio.to_thread(controller.state.prepare_session_directory_sync, path)
            if session_dir is None:
                self.logger.error(
                    "Unable to refresh session directory after path change; leaving previous session active",
                )
                return
            controller.session_dir = session_dir
            for slot in controller._previews:
                await self.start_storage_resources(slot)
