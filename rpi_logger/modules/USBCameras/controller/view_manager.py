"""Helper utilities for USBCameraController view/state updates."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from rpi_logger.core.logging_utils import get_module_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .runtime import USBCameraController
    from .slot import USBCameraSlot

logger = get_module_logger(__name__)


class USBViewManager:
    """Encapsulates USBCameraController interactions with the view adapter."""

    def __init__(self, controller: "USBCameraController") -> None:
        self._controller = controller

    @property
    def adapter(self):
        return self._controller.view_adapter

    def set_status(self, message: str, *, level: int = logging.INFO) -> None:
        self._controller.state.update_status(message, level=level)
        logger.debug("View status updated | level=%s message=%s", level, message)

    def refresh_status(self) -> None:
        controller = self._controller
        slots = controller._slots
        active_cameras = sum(
            1 for slot in slots if slot.camera is not None and not getattr(slot, "capture_paused", False)
        )
        if active_cameras == 0:
            message = "No cameras detected"
        else:
            suffix = "s" if active_cameras != 1 else ""
            message = f"{active_cameras} camera{suffix} active"

        if controller.save_enabled:
            target_dir = controller.save_dir or controller.session_dir
            if target_dir:
                message += f" | saving to {target_dir}"
            else:
                message += " | saving enabled"
        self.set_status(message)
        self.publish_pipeline_metrics()

    def refresh_preview_layout(self) -> None:
        adapter = self.adapter
        if adapter:
            adapter.refresh_preview_layout(self._controller._slots)

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

    def compute_stage_fps(self) -> dict[str, float]:
        controller = self._controller
        stage_keys = ("capture_fps", "process_fps", "preview_fps", "storage_fps")
        metrics = {key: 0.0 for key in stage_keys}
        active_slots = [
            slot for slot in controller._slots if slot.camera is not None and not getattr(slot, "capture_paused", False)
        ]
        if not active_slots:
            return metrics

        for key in stage_keys:
            values = [getattr(slot, key, 0.0) for slot in active_slots if getattr(slot, key, 0.0) > 0.0]
            metrics[key] = sum(values) / len(values) if values else 0.0
        return metrics

    async def run_metrics_loop(self) -> None:
        controller = self._controller
        while not controller._stop_event.is_set():
            self.publish_pipeline_metrics()
            await asyncio.sleep(controller.UPDATE_INTERVAL)
        self.publish_pipeline_metrics()

    def handle_preview_resize(self, slot: "USBCameraSlot", width: int, height: int) -> None:
        new_size = (width, height)
        if new_size == slot.size:
            return
        slot.size = new_size
        self.refresh_preview_layout()


__all__ = ["USBViewManager"]
