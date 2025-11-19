"""Pipeline consumers shared by the Cameras controller."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import numpy as np
from PIL import Image

try:  # Pillow 10+
    DEFAULT_RESAMPLE = Image.Resampling.BILINEAR
except AttributeError:  # pragma: no cover - compatibility shim
    DEFAULT_RESAMPLE = Image.BILINEAR  # type: ignore[attr-defined]

from ..domain.model import FramePayload, RollingFpsCounter
from ..io.storage import StorageWriteResult
from rpi_logger.core.logging_utils import ensure_structured_logger
from ..ui import CameraViewAdapter
from .slot import CameraSlot


@dataclass(slots=True)
class StorageHooks:
    """Callback bundle used by the storage consumer."""

    save_enabled: Callable[[], bool]
    session_dir_provider: Callable[[], Optional[Path]]
    save_stills_enabled: Callable[[], bool]
    frame_to_image: Callable[[Any, str, Optional[tuple[int, int]]], Image.Image]
    resolve_video_fps: Callable[[CameraSlot], float]
    on_frame_written: Callable[[CameraSlot, FramePayload, StorageWriteResult, int], Awaitable[bool]]
    handle_failure: Callable[[CameraSlot, str], Awaitable[None]]


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


class StorageConsumer:
    """Persists frames using the per-camera storage pipeline."""

    def __init__(
        self,
        *,
        stop_event: asyncio.Event,
        hooks: StorageHooks,
        logger: logging.Logger,
    ) -> None:
        self._stop_event = stop_event
        self._hooks = hooks
        self._logger = ensure_structured_logger(
            logger,
            component="StorageConsumer",
            fallback_name=f"{__name__}.StorageConsumer",
        )

    async def run(self, slot: CameraSlot) -> None:
        queue = slot.storage_queue
        if queue is None:
            return

        while True:
            if self._stop_event.is_set() and queue.empty():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:  # pragma: no cover
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
                if not self._hooks.save_enabled() or self._hooks.session_dir_provider() is None:
                    continue

                frame = latest.frame
                pipeline = slot.storage_pipeline
                if frame is None or pipeline is None:
                    continue

                fps_hint = self._hooks.resolve_video_fps(slot)
                uses_hw_encoder = pipeline.uses_hardware_encoder
                need_stills = self._hooks.save_stills_enabled()
                rgb_frame: Optional[np.ndarray] = None
                still_image: Optional[Image.Image] = None
                pixel_format = latest.pixel_format or slot.main_format or slot.preview_format

                if uses_hw_encoder and not need_stills:
                    storage_result = await pipeline.write_frame(
                        None,
                        latest,
                        fps_hint=fps_hint,
                        pil_image=None,
                    )
                else:
                    image = await asyncio.to_thread(
                        self._hooks.frame_to_image,
                        frame,
                        pixel_format,
                        size_hint=slot.main_size,
                    )
                    target_size = slot.save_size or slot.main_size
                    if target_size and image.size != target_size:
                        image = await asyncio.to_thread(image.resize, target_size, DEFAULT_RESAMPLE)
                    if image.mode != "RGB":
                        image = await asyncio.to_thread(image.convert, "RGB")
                    if not uses_hw_encoder:
                        rgb_frame = np.asarray(image)
                    if need_stills:
                        still_image = image
                    storage_result = await pipeline.write_frame(
                        rgb_frame,
                        latest,
                        fps_hint=fps_hint,
                        pil_image=still_image,
                    )

                should_continue = await self._hooks.on_frame_written(
                    slot,
                    latest,
                    storage_result,
                    slot.storage_drop_since_last,
                )
                slot.storage_drop_since_last = 0
                if not should_continue:
                    break
            except RuntimeError as exc:
                await self._hooks.handle_failure(slot, str(exc))
                break
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning("Storage consumer error (camera %s): %s", slot.index, exc)
            finally:
                queue.task_done()


__all__ = ["PreviewConsumer", "StorageConsumer", "StorageHooks"]
