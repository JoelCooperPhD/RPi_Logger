"""Preview pipeline for Cameras."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CameraId, ModeSelection
from rpi_logger.modules.Cameras.runtime.metrics import FPSCounter, TimingTracker
from rpi_logger.modules.Cameras.runtime.tasks import TaskManager

PreviewConsumer = Callable[[Any], asyncio.Future | asyncio.Task | None]


class PreviewPipeline:
    """Consumes frames from router and pushes to UI worker with FPS cap/backpressure."""

    def __init__(
        self,
        *,
        logger: LoggerLike = None,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._task_manager = TaskManager(logger=self._logger)
        self._fps = FPSCounter()
        self._timing = TimingTracker()
        self._drops: dict[str, int] = {}
        self._fps_metrics: dict[str, FPSCounter] = {}
        self._last_snapshot: dict[str, dict[str, float]] = {}
        self._target_fps: dict[str, float | None] = {}
        self._keep_every: dict[str, int | None] = {}
        self._emit_counts: dict[str, int] = {}

    def start(
        self,
        camera_id: CameraId,
        source_queue: asyncio.Queue,
        consumer: PreviewConsumer,
        selection: ModeSelection,
    ) -> None:
        key = camera_id.key
        task_name = f"preview:{key}"
        self._drops[key] = 0
        self._fps_metrics[key] = FPSCounter()
        self._last_snapshot[key] = {"preview_fps_instant": 0.0, "preview_fps_avg": 0.0}
        self._target_fps[key] = selection.target_fps
        self._keep_every[key] = selection.keep_every
        self._emit_counts[key] = 0
        self._task_manager.create(task_name, self._loop(camera_id, source_queue, consumer, selection))
        self._logger.info("Preview pipeline started for %s", key)

    async def stop(self, camera_id: CameraId) -> None:
        await self._task_manager.cancel(f"preview:{camera_id.key}")
        self._drops.pop(camera_id.key, None)
        self._fps_metrics.pop(camera_id.key, None)
        self._last_snapshot.pop(camera_id.key, None)
        self._target_fps.pop(camera_id.key, None)
        self._keep_every.pop(camera_id.key, None)
        self._emit_counts.pop(camera_id.key, None)

    def set_target_fps(self, camera_id: CameraId, target_fps: float | None) -> None:
        """Update target FPS clamp without restarting the pipeline."""

        self._target_fps[camera_id.key] = target_fps

    def set_keep_every(self, camera_id: CameraId, keep_every: int | None) -> None:
        """Update frame sampling ratio (1 in N)."""

        key = camera_id.key
        self._keep_every[key] = keep_every
        self._emit_counts[key] = 0

    async def _loop(
        self,
        camera_id: CameraId,
        queue: asyncio.Queue,
        consumer: PreviewConsumer,
        selection: ModeSelection,
    ) -> None:
        key = camera_id.key
        last_emit = 0.0
        emit_count = 0
        try:
            while True:
                frame = await queue.get()
                if frame is None:
                    break
                keep_every = self._keep_every.get(key, selection.keep_every)
                if keep_every and keep_every > 1:
                    emit_count = self._emit_counts.get(key, emit_count) + 1
                    self._emit_counts[key] = emit_count
                    if ((emit_count - 1) % keep_every) != 0:
                        self._drops[key] = self._drops.get(key, 0) + 1
                        queue.task_done()
                        continue
                target_fps = self._target_fps.get(key, selection.target_fps)
                target_interval = 1.0 / target_fps if target_fps else 0.0
                now = asyncio.get_running_loop().time()
                if target_interval and (now - last_emit) < target_interval:
                    self._drops[key] = self._drops.get(key, 0) + 1
                    queue.task_done()
                    continue
                last_emit = now
                fps_counter = self._fps_metrics.get(key, self._fps)
                snapshot = fps_counter.update()
                self._last_snapshot[key] = {
                    "preview_fps_instant": round(snapshot.instant, 2),
                    "preview_fps_avg": round(snapshot.average, 2),
                }
                self._timing.record(now)
                try:
                    consumer(frame)
                except Exception:  # pragma: no cover - defensive logging
                    self._logger.exception("Preview consumer error for %s", key)
                queue.task_done()
        except asyncio.CancelledError:
            self._logger.debug("Preview loop cancelled for %s", key)
            raise
        finally:
            if not queue.empty():
                try:
                    queue.task_done()
                except Exception:
                    pass

    def metrics(self, camera_id: CameraId) -> dict[str, float | int]:
        key = camera_id.key
        return {
            **self._last_snapshot.get(key, {}),
            "preview_dropped": self._drops.get(key, 0),
        }
