"""Frame router for preview/record fanout."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CameraId, ModeSelection, SelectedConfigs
from rpi_logger.modules.Cameras.runtime.backends import DeviceLost
from rpi_logger.modules.Cameras.runtime.metrics import FPSCounter
from rpi_logger.modules.Cameras.runtime.tasks import TaskManager


@dataclass(slots=True)
class RouterQueues:
    preview: asyncio.Queue
    record: asyncio.Queue


@dataclass(slots=True)
class RouterMetrics:
    preview_dropped: int = 0
    record_backpressure: int = 0
    preview_enqueued: int = 0
    record_enqueued: int = 0
    last_preview_q: int = 0
    last_record_q: int = 0
    ingress_fps_avg: float = 0.0
    ingress_fps_inst: float = 0.0
    ingress_wait_ms: float = 0.0


class Router:
    """Fan out frames from backends to preview/record queues with backpressure handling."""

    def __init__(self, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._queues: Dict[str, RouterQueues] = {}
        self._task_manager = TaskManager(logger=self._logger)
        self._metrics: Dict[str, RouterMetrics] = {}
        self._preview_enabled: Dict[str, bool] = {}
        self._record_enabled: Dict[str, bool] = {}
        self._wake_events: Dict[str, asyncio.Event] = {}
        self._ingress_fps: Dict[str, FPSCounter] = {}

    def attach(
        self,
        camera_id: CameraId,
        backend_handle: Any,
        configs: SelectedConfigs,
        *,
        shared: bool = True,
        preview_queue_size: int = 2,
        record_queue_size: int = 4,
        preview_enabled: bool = True,
        record_enabled: bool = False,
    ) -> None:
        """Attach router tasks for a camera."""

        key = camera_id.key
        if key in self._queues:
            return
        preview_q: asyncio.Queue = asyncio.Queue(maxsize=preview_queue_size)
        record_q: asyncio.Queue = asyncio.Queue(maxsize=record_queue_size)
        self._queues[key] = RouterQueues(preview=preview_q, record=record_q)
        self._metrics[key] = RouterMetrics()
        self._preview_enabled[key] = preview_enabled
        self._record_enabled[key] = record_enabled
        self._ingress_fps[key] = FPSCounter(window_size=120)
        wake_event = asyncio.Event()
        if preview_enabled or record_enabled:
            wake_event.set()
        self._wake_events[key] = wake_event
        task_name = f"router:{key}"
        self._task_manager.create(task_name, self._run_router(camera_id, backend_handle, configs, shared))
        self._logger.info("Router attached for %s (shared=%s)", key, shared)

    def set_preview_enabled(self, camera_id: CameraId, enabled: bool) -> None:
        key = camera_id.key
        self._preview_enabled[key] = enabled
        event = self._wake_events.get(key)
        if not event:
            return
        if enabled or self._record_enabled.get(key, False):
            event.set()
        else:
            event.clear()

    def set_record_enabled(self, camera_id: CameraId, enabled: bool) -> None:
        key = camera_id.key
        self._record_enabled[key] = enabled
        event = self._wake_events.get(key)
        if event:
            if enabled or self._preview_enabled.get(key, False):
                event.set()
            else:
                event.clear()
        if not enabled:
            queues = self._queues.get(key)
            if queues:
                while not queues.record.empty():
                    try:
                        queues.record.get_nowait()
                        queues.record.task_done()
                    except Exception:
                        break

    async def _run_router(
        self,
        camera_id: CameraId,
        backend_handle: Any,
        configs: SelectedConfigs,
        shared: bool,
    ) -> None:
        key = camera_id.key
        queues = self._queues.get(key)
        if not queues:
            return

        metrics = self._metrics.get(key)
        wake_event = self._wake_events.get(key)
        frame_iter = None
        frames_fn = getattr(backend_handle, "frames", None)
        if callable(frames_fn):
            frame_iter = frames_fn()
        first_frame_logged = False

        try:
            while True:
                if not self._is_stream_enabled(key):
                    if wake_event:
                        wake_event.clear()
                        await wake_event.wait()
                    else:
                        await asyncio.sleep(0.05)
                    continue
                if frame_iter is not None:
                    try:
                        frame = await frame_iter.__anext__()  # type: ignore[attr-defined]
                    except StopAsyncIteration:
                        break
                else:
                    frame = await backend_handle.read_frame()  # type: ignore[attr-defined]
                fps_counter = self._ingress_fps.get(key)
                if fps_counter and metrics:
                    frame_ts = getattr(frame, "timestamp", None)
                    if frame_ts is None:
                        try:
                            frame_ts = asyncio.get_running_loop().time()
                        except Exception:
                            frame_ts = None
                    snap = fps_counter.update(frame_ts)
                    metrics.ingress_fps_avg = round(snap.average, 2)
                    metrics.ingress_fps_inst = round(snap.instant, 2)
                    wait_ms = getattr(frame, "wait_ms", None)
                    if isinstance(wait_ms, (int, float)):
                        metrics.ingress_wait_ms = float(wait_ms)
                if not first_frame_logged:
                    shape = getattr(getattr(frame, "data", frame), "shape", None)
                    dtype = getattr(getattr(frame, "data", frame), "dtype", None)
                    self._logger.info("Router received first frame %s shape=%s dtype=%s", key, shape, dtype)
                    first_frame_logged = True
                await self._fanout_frame(key, frame, queues, configs, metrics)
        except DeviceLost:
            self._logger.warning("Backend device lost for %s", key)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive logging
            self._logger.exception("Router error for %s", key)
        finally:
            queues.preview.put_nowait(None)
            queues.record.put_nowait(None)

    async def _fanout_frame(
        self,
        key: str,
        frame: Any,
        queues: RouterQueues,
        configs: SelectedConfigs,
        metrics: Optional[RouterMetrics],
    ) -> None:
        preview_on = self._preview_enabled.get(key, True)
        record_on = self._record_enabled.get(key, False)
        dropped = False
        waited = False
        if preview_on:
            dropped, _ = await _enqueue_coalescing(queues.preview, frame, drop_oldest=True)
        if record_on:
            _dropped_record, waited = await _enqueue_coalescing(queues.record, frame, drop_oldest=False)
        if metrics:
            if dropped:
                metrics.preview_dropped += 1
            if waited:
                metrics.record_backpressure += 1
            if preview_on:
                metrics.preview_enqueued += 1
                metrics.last_preview_q = queues.preview.qsize()
            if record_on:
                metrics.record_enqueued += 1
                metrics.last_record_q = queues.record.qsize()

    def get_preview_queue(self, camera_id: CameraId) -> Optional[asyncio.Queue]:
        entry = self._queues.get(camera_id.key)
        return entry.preview if entry else None

    def get_record_queue(self, camera_id: CameraId) -> Optional[asyncio.Queue]:
        entry = self._queues.get(camera_id.key)
        return entry.record if entry else None

    async def stop(self, camera_id: CameraId) -> None:
        key = camera_id.key
        await self._task_manager.cancel(f"router:{key}")
        self._queues.pop(key, None)
        self._metrics.pop(key, None)
        self._preview_enabled.pop(key, None)
        self._record_enabled.pop(key, None)
        self._wake_events.pop(key, None)
        self._ingress_fps.pop(key, None)

    async def stop_all(self) -> None:
        for key in list(self._queues.keys()):
            backend, _, stable_id = key.partition(":")
            await self.stop(CameraId(backend=backend, stable_id=stable_id or key))
        await self._task_manager.cancel_all()

    def metrics_for(self, camera_id: CameraId) -> Optional[RouterMetrics]:
        return self._metrics.get(camera_id.key)

    def _is_stream_enabled(self, key: str) -> bool:
        return self._preview_enabled.get(key, False) or self._record_enabled.get(key, False)


# ---------------------------------------------------------------------------
# Queue helpers


async def _enqueue_coalescing(queue: asyncio.Queue, item: Any, *, drop_oldest: bool) -> tuple[bool, bool]:
    """Attempt to enqueue; returns (dropped, waited_for_space)."""

    dropped = False
    waited = False
    try:
        queue.put_nowait(item)
        return dropped, waited
    except asyncio.QueueFull:
        if drop_oldest:
            try:
                _ = queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                dropped = True
                return dropped, waited
            dropped = True
        else:
            # Wait for space
            waited = True
            await queue.put(item)
    return dropped, waited
