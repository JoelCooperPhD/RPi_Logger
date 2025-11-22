"""Preview worker that dispatches frames to UI callbacks."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger

PreviewDispatch = Callable[[Any], None]


class PreviewWorker:
    """Reads frames from queue and dispatches to a UI-safe callback."""

    def __init__(self, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._task: Optional[asyncio.Task] = None

    def start(self, queue: asyncio.Queue, dispatch: PreviewDispatch) -> None:
        if self._task:
            return
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._loop(queue, dispatch), name="PreviewWorker")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self, queue: asyncio.Queue, dispatch: PreviewDispatch) -> None:
        try:
            while True:
                frame = await queue.get()
                if frame is None:
                    break
                try:
                    dispatch(frame)
                except Exception:  # pragma: no cover - defensive logging
                    self._logger.exception("Preview dispatch failed")
                queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            queue.task_done()
