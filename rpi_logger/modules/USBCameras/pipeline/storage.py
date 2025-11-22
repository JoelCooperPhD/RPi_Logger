"""Storage pipeline consumer for USB cameras."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import cv2
import numpy as np

from rpi_logger.core.logging_utils import ensure_structured_logger
from rpi_logger.modules.USBCameras.domain.frame import FramePayload
from rpi_logger.modules.USBCameras.pipeline.hooks import StorageHooks
from rpi_logger.modules.USBCameras.controller.slot import USBCameraSlot


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

    async def run(self, slot: USBCameraSlot) -> None:
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
                frame_array = frame if isinstance(frame, np.ndarray) else np.asarray(frame)
                is_planar_yuv = frame_array.ndim == 2
                yuv_format = str(pixel_format or "").upper()
                prefers_yuv = pipeline.accepts_yuv and (is_planar_yuv or yuv_format.startswith(("YUV", "NV12")))

                if uses_hw_encoder:
                    storage_result = await pipeline.write_frame(
                        None,
                        latest,
                        fps_hint=fps_hint,
                    )
                elif prefers_yuv:
                    storage_result = await pipeline.write_frame(
                        None,
                        latest,
                        fps_hint=fps_hint,
                        yuv_frame=frame_array,
                    )
                else:
                    bgr_frame = await asyncio.to_thread(
                        self._hooks.frame_to_bgr,
                        frame_array,
                        pixel_format,
                        size_hint=slot.main_size,
                    )
                    target_size = slot.save_size or slot.main_size
                    if target_size and (
                        bgr_frame.shape[1] != target_size[0] or bgr_frame.shape[0] != target_size[1]
                    ):
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


__all__ = ["StorageConsumer"]
