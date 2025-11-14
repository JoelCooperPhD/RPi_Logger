"""Helper utilities for CameraController view/state updates."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from ..logging_utils import get_module_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .runtime import CameraController
    from .slot import CameraSlot

logger = get_module_logger(__name__)


class CameraViewManager:
    """Encapsulates CameraController interactions with the view adapter."""

    def __init__(self, controller: "CameraController") -> None:
        self._controller = controller

    @property
    def adapter(self):  # noqa: D401 - lightweight passthrough
        """Return the controller's view adapter (may be None)."""
        return self._controller.view_adapter

    def set_status(self, message: str, *, level: int = logging.INFO) -> None:
        self._controller.state.update_status(message, level=level)
        logger.debug("View status updated | level=%s message=%s", level, message)

    def install_view_hooks(self) -> None:
        adapter = self.adapter
        if not adapter:
            return
        adapter.install_preview_fps_menu(
            getter=lambda: self._controller.preview_fraction,
            handler=self._controller.capture_settings.handle_preview_fraction_selection,
        )

    def sync_record_toggle(self) -> None:
        adapter = self.adapter
        controller = self._controller
        if not adapter:
            return
        desired = bool(controller.save_enabled or controller.capture_preferences_enabled)
        adapter.sync_record_toggle(
            desired,
            capture_disabled=controller.save_enabled,
        )

    def register_camera_toggle(self, slot: "CameraSlot") -> None:
        adapter = self.adapter
        if not adapter:
            return
        adapter.register_camera_toggle(
            index=slot.index,
            title=slot.title,
            enabled=slot.preview_enabled,
            handler=self.handle_camera_toggle_request,
        )
        logger.debug(
            "Camera toggle registered | index=%s enabled=%s title=%s",
            slot.index,
            slot.preview_enabled,
            slot.title,
        )

    async def handle_camera_toggle_request(self, index: int, enabled: bool) -> None:
        slot = self._slot_by_index(index)
        controller = self._controller
        if slot is None or slot.preview_enabled == enabled:
            return
        slot.preview_enabled = enabled
        if enabled:
            resumed = await controller.resume_camera_slot(slot)
            if not resumed:
                slot.preview_enabled = False
                if self.adapter:
                    self.adapter.update_camera_toggle_state(index, False)
                    self.adapter.show_camera_hidden(slot)
                self.refresh_status()
                return
            slot.preview_gate.configure(slot.preview_gate.period)
            if self.adapter:
                self.adapter.show_camera_waiting(slot)
        else:
            await controller.pause_camera_slot(slot)
            if self.adapter:
                self.adapter.show_camera_hidden(slot)
        self.refresh_status()
        self.refresh_preview_layout()

    def refresh_preview_layout(self) -> None:
        adapter = self.adapter
        if adapter:
            adapter.refresh_preview_layout(self._controller._previews)
            logger.debug("Preview layout refreshed | slots=%s", len(self._controller._previews))

    def refresh_status(self) -> None:
        controller = self._controller
        previews = controller._previews
        active_cameras = sum(
            1 for slot in previews if slot.camera is not None and not getattr(slot, "capture_paused", False)
        )
        if active_cameras == 0:
            message = "No cameras detected"
            if controller.save_enabled:
                if controller.save_dir:
                    message += f" | saving enabled -> {controller.save_dir}"
                else:
                    message += " | saving enabled"
        else:
            suffix = "s" if active_cameras != 1 else ""
            message = f"{active_cameras} camera{suffix} active"
            if controller.save_enabled:
                target_dir = controller.save_dir or controller.session_dir
                if target_dir:
                    message += f" | saving to {target_dir}"
                else:
                    message += " | saving enabled"
                if controller.session_dir:
                    message += f" | session {controller.session_dir.name}"
            else:
                if controller.capture_preferences_enabled:
                    message += " | saving disabled (awaiting logger start)"
                else:
                    message += " | saving disabled"

        metrics = self.compute_stage_fps()
        stage_summary = self.format_stage_status(metrics)
        if stage_summary:
            message += f" | {stage_summary}"

        logical = controller.setup_manager.get_requested_resolution()
        if logical:
            message += f" | logical res={logical[0]}x{logical[1]} (software)"

        if controller.save_enabled:
            drop_total = sum(slot.storage_drop_total for slot in previews)
            if drop_total:
                message += f" | queue drops {drop_total}"
            if not controller.save_stills_enabled:
                message += " | stills=off"
            fps_values = [slot.last_video_fps for slot in previews if slot.last_video_fps > 0]
            if fps_values:
                avg_fps = sum(fps_values) / len(fps_values)
                message += f" | fps≈{avg_fps:.1f}"

        self.set_status(message)
        logger.debug("View status composed | message=%s", message)
        self.publish_pipeline_metrics()

    def refresh_preview_fps_ui(self) -> None:
        adapter = self.adapter
        if adapter:
            adapter.refresh_preview_fps_ui()

    def compute_stage_fps(self) -> dict[str, float]:
        controller = self._controller
        stage_keys = ("capture_fps", "process_fps", "preview_fps", "storage_fps")
        metrics = {key: 0.0 for key in stage_keys}
        active_slots = [
            slot for slot in controller._previews if slot.camera is not None and not getattr(slot, "capture_paused", False)
        ]
        if not active_slots:
            return metrics

        for key in stage_keys:
            values = [getattr(slot, key, 0.0) for slot in active_slots if getattr(slot, key, 0.0) > 0.0]
            metrics[key] = sum(values) / len(values) if values else 0.0
        return metrics

    @staticmethod
    def format_stage_status(metrics: dict[str, float]) -> str:
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

    def publish_pipeline_metrics(self) -> None:
        adapter = self.adapter
        if not adapter:
            return
        metrics = self.compute_stage_fps()
        adapter.update_pipeline_metrics(
            capture_fps=metrics.get("capture_fps", 0.0),
            process_fps=metrics.get("process_fps", 0.0),
            preview_fps=metrics.get("preview_fps", 0.0),
            storage_fps=metrics.get("storage_fps", 0.0),
        )
        logger.debug(
            "Pipeline metrics published | capture=%.2f process=%.2f preview=%.2f storage=%.2f",
            metrics.get("capture_fps", 0.0),
            metrics.get("process_fps", 0.0),
            metrics.get("preview_fps", 0.0),
            metrics.get("storage_fps", 0.0),
        )

    async def run_metrics_loop(self) -> None:
        controller = self._controller
        while not controller._stop_event.is_set():
            self.publish_pipeline_metrics()
            await asyncio.sleep(controller.UPDATE_INTERVAL)
        self.publish_pipeline_metrics()

    def _slot_by_index(self, index: int) -> Optional["CameraSlot"]:
        for slot in self._controller._previews:
            if slot.index == index:
                return slot
        return None

    def handle_preview_resize(self, slot: "CameraSlot", width: int, height: int) -> None:
        new_size = (width, height)
        if new_size == slot.size:
            return
        slot.size = new_size
