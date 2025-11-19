"""Pipeline consumers shared by the Cameras controller."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import numpy as np
import numpy as np


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
    frame_to_bgr: Callable[[Any, str, Optional[tuple[int, int]]], np.ndarray]
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
                pixel_format = latest.pixel_format or slot.main_format or slot.preview_format
                
                if uses_hw_encoder:
                    storage_result = await pipeline.write_frame(
                        None,
                        latest,
                        fps_hint=fps_hint,
                    )
                elif pipeline.accepts_yuv:
                    # Optimization: Pass raw YUV frame for ffmpeg
                    
                    yuv_frame = frame if isinstance(frame, np.ndarray) else np.asarray(frame)
                    
                    storage_result = await pipeline.write_frame(
                        None,
                        latest,
                        fps_hint=fps_hint,
                        yuv_frame=yuv_frame,
                    )
                else:
                    # Optimization: Convert directly to BGR for video if possible
                    bgr_frame: Optional[np.ndarray] = None
                    
                    bgr_frame = await asyncio.to_thread(
                        self._hooks.frame_to_bgr,
                        frame,
                        pixel_format,
                        size_hint=slot.main_size,
                    )
                    target_size = slot.save_size or slot.main_size
                    if target_size and (bgr_frame.shape[1] != target_size[0] or bgr_frame.shape[0] != target_size[1]):
                        bgr_frame = await asyncio.to_thread(
                            cv2.resize,
                            bgr_frame,
                            target_size,
                            interpolation=cv2.INTER_LINEAR,
                        )

                    storage_result = await pipeline.write_frame(
                        bgr_frame,
                        latest,
                        fps_hint=fps_hint,
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
