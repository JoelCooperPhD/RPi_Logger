"""Fan-out router that forwards frames to preview and record queues."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CameraId, SelectedConfigs
from rpi_logger.modules.Cameras.runtime.metrics import FPSCounter
from rpi_logger.modules.Cameras.runtime.tasks import TaskManager


@dataclass(slots=True)
class RouterMetrics:
    preview_dropped: int = 0
    record_backpressure: int = 0
    preview_enqueued: int = 0
    record_enqueued: int = 0
    record_dropped: int = 0
    ingress_fps_avg: float = 0.0
    ingress_fps_inst: float = 0.0
    ingress_wait_ms: float = 0.0


class Router:
    """Routes frames from a backend handle to preview/record queues."""

    def __init__(self, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._task_manager = TaskManager(logger=self._logger)
        self._preview_queues: dict[str, asyncio.Queue] = {}
        self._record_queues: dict[str, asyncio.Queue] = {}
        self._preview_enabled: dict[str, bool] = {}
        self._record_enabled: dict[str, bool] = {}
        self._metrics: dict[str, RouterMetrics] = {}
        self._fps: dict[str, FPSCounter] = {}

    def attach(
        self,
        camera_id: CameraId,
        handle: Any,
        configs: SelectedConfigs,
        *,
        preview_queue_size: int = 8,
        record_queue_size: int = 8,
    ) -> None:
        key = camera_id.key
        self._preview_queues[key] = asyncio.Queue(maxsize=preview_queue_size)
        self._record_queues[key] = asyncio.Queue(maxsize=record_queue_size)
        self._preview_enabled[key] = True
        self._record_enabled[key] = False
        self._metrics[key] = RouterMetrics()
        self._fps[key] = FPSCounter()
        self._task_manager.create(f"router:{key}", self._loop(camera_id, handle))

    async def stop(self, camera_id: CameraId) -> None:
        key = camera_id.key
        await self._task_manager.cancel(f"router:{key}")
        await self._close_queue(self._preview_queues.pop(key, None))
        await self._close_queue(self._record_queues.pop(key, None))
        self._preview_enabled.pop(key, None)
        self._record_enabled.pop(key, None)
        self._metrics.pop(key, None)
        self._fps.pop(key, None)

    async def stop_all(self) -> None:
        await self._task_manager.cancel_all()
        for q in list(self._preview_queues.values()):
            await self._close_queue(q)
        for q in list(self._record_queues.values()):
            await self._close_queue(q)
        self._preview_queues.clear()
        self._record_queues.clear()
        self._preview_enabled.clear()
        self._record_enabled.clear()
        self._metrics.clear()
        self._fps.clear()

    def get_preview_queue(self, camera_id: CameraId) -> Optional[asyncio.Queue]:
        return self._preview_queues.get(camera_id.key)

    def get_record_queue(self, camera_id: CameraId) -> Optional[asyncio.Queue]:
        return self._record_queues.get(camera_id.key)

    def metrics_for(self, camera_id: CameraId) -> Optional[RouterMetrics]:
        return self._metrics.get(camera_id.key)

    def set_record_enabled(self, camera_id: CameraId, enabled: bool) -> None:
        """Toggle record enqueue for a camera without restarting the router."""

        key = camera_id.key
        if key not in self._record_queues:
            return
        self._record_enabled[key] = enabled
        if not enabled:
            # Drain any queued frames to avoid backpressure when idle.
            self._drain_queue(self._record_queues.get(key))

    def set_preview_enabled(self, camera_id: CameraId, enabled: bool) -> None:
        """Toggle preview enqueue for a camera without restarting the router."""

        key = camera_id.key
        if key not in self._preview_queues:
            return
        self._preview_enabled[key] = enabled
        if not enabled:
            self._drain_queue(self._preview_queues.get(key))

    # ------------------------------------------------------------------
    async def _loop(self, camera_id: CameraId, handle: Any) -> None:
        key = camera_id.key
        pq = self._preview_queues[key]
        rq = self._record_queues[key]
        metrics = self._metrics[key]
        fps_counter = self._fps[key]

        async def _iter_frames():
            if hasattr(handle, "frames") and callable(handle.frames):
                async for frame in handle.frames():
                    yield frame
            elif hasattr(handle, "read_frame") and callable(handle.read_frame):
                while True:
                    yield await handle.read_frame()
            else:
                return

        try:
            async for frame in _iter_frames():
                snapshot = fps_counter.update(getattr(frame, "timestamp", None))
                metrics.ingress_fps_inst = snapshot.instant
                metrics.ingress_fps_avg = snapshot.average
                wait_ms = getattr(frame, "wait_ms", None)
                if wait_ms is not None:
                    metrics.ingress_wait_ms = wait_ms

                # Preview (drop if full)
                if self._preview_enabled.get(key, True):
                    dropped = False
                    while True:
                        try:
                            pq.put_nowait(frame)
                            metrics.preview_enqueued += 1
                            if dropped:
                                metrics.preview_dropped += 1
                            break
                        except asyncio.QueueFull:
                            dropped = True
                            try:
                                pq.get_nowait()
                            except Exception:
                                break

                # Record (apply backpressure only when enabled)
                if self._record_enabled.get(key, False):
                    dropped_for_storage = 0
                    while True:
                        try:
                            if dropped_for_storage and hasattr(frame, "storage_queue_drops"):
                                try:
                                    frame.storage_queue_drops = dropped_for_storage  # type: ignore[attr-defined]
                                except Exception:
                                    pass
                            rq.put_nowait(frame)
                            metrics.record_enqueued += 1
                            break
                        except asyncio.QueueFull:
                            metrics.record_backpressure += 1
                            metrics.record_dropped += 1
                            dropped_for_storage += 1
                            try:
                                dropped = rq.get_nowait()
                                # Keep Queue unfinished task counts in balance if join() is used elsewhere.
                                try:
                                    rq.task_done()
                                except Exception:
                                    pass
                                # Make sure we do not accidentally discard the sentinel.
                                if dropped is None:
                                    rq.put_nowait(None)
                                    break
                            except asyncio.QueueEmpty:
                                pass
                            await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        finally:
            await self._close_queue(pq)
            await self._close_queue(rq)

    async def _close_queue(self, queue: Optional[asyncio.Queue]) -> None:
        if not queue:
            return
        try:
            queue.put_nowait(None)
        except Exception:
            pass

    def _drain_queue(self, queue: Optional[asyncio.Queue]) -> None:
        if not queue:
            return
        try:
            while not queue.empty():
                queue.get_nowait()
                queue.task_done()
        except Exception:
            pass


__all__ = ["Router", "RouterMetrics"]
