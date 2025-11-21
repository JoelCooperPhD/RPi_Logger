"""Preview pipeline consumer for the Cameras module."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from rpi_logger.core.logging_utils import ensure_structured_logger
from ..domain.model import FramePayload, RollingFpsCounter
from ..ui import CameraViewAdapter
from ..controller.slot import CameraSlot


class PreviewConsumer:
    """De-queues preview frames and hands them to the view adapter."""

    def __init__(
        self,
        *,
        stop_event: asyncio.Event,
        view_adapter: Optional[CameraViewAdapter],
        logger: logging.Logger,
    ) -> None:
        self._stop_event = stop_event
        self._view = view_adapter
        self._logger = ensure_structured_logger(
            logger,
            component="PreviewConsumer",
            fallback_name=f"{__name__}.PreviewConsumer",
        )
        self._fps_counters: dict[int, RollingFpsCounter] = {}

    async def run(self, slot: CameraSlot) -> None:
        queue = slot.preview_queue
        if queue is None:
            return

        while True:
            if self._stop_event.is_set() and queue.empty():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
                break

            batch = [payload]
            while True:
                try:
                    extra = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                batch.append(extra)

            if any(item is None for item in batch):
                for item in batch:
                    queue.task_done()
                break

            latest = batch[-1]
            for item in batch[:-1]:
                queue.task_done()

            try:
                if latest.frame is None or not self._view:
                    continue
                updated = await self._view.display_frame(
                    slot,
                    latest.frame,
                    latest.pixel_format or slot.preview_format or slot.main_format,
                )
                if updated:
                    self._record_view_frame(slot)
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning("Preview consumer error (camera %s): %s", slot.index, exc)
            finally:
                queue.task_done()

    def _record_view_frame(self, slot: CameraSlot) -> None:
        counter = self._fps_counters.get(slot.index)
        if counter is None:
            counter = RollingFpsCounter()
            self._fps_counters[slot.index] = counter
        slot.preview_fps = counter.tick()


__all__ = ["PreviewConsumer"]
