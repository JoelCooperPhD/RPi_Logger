"""Async task tracking helpers for Cameras2."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger


TaskErrorHandler = Callable[[str, BaseException], None]


class TaskManager:
    """Owns asyncio tasks for preview/record/discovery pipelines with clean shutdown."""

    def __init__(
        self,
        *,
        shutdown_event: Optional[asyncio.Event] = None,
        logger: LoggerLike = None,
        on_task_error: Optional[TaskErrorHandler] = None,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._shutdown_event = shutdown_event or asyncio.Event()
        self._tasks: Dict[str, asyncio.Task[Any]] = {}
        self._on_task_error = on_task_error

    # ------------------------------------------------------------------
    # Task lifecycle

    def create(
        self,
        name: str,
        coro: Awaitable[Any],
        *,
        shield: bool = False,
    ) -> asyncio.Task[Any]:
        """Spawn a tracked task with consistent logging."""

        if self._shutdown_event.is_set():
            raise RuntimeError(f"Cannot create task {name}; shutdown already requested")

        wrapped = coro if not shield else asyncio.shield(coro)
        task = asyncio.create_task(self._run_task(name, wrapped), name=name)
        self._tasks[name] = task
        task.add_done_callback(lambda t: self._tasks.pop(name, None))
        self._logger.debug("Task created: %s", name)
        return task

    async def _run_task(self, name: str, coro: Awaitable[Any]) -> Any:
        try:
            return await coro
        except asyncio.CancelledError:
            self._logger.debug("Task cancelled: %s", name)
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.exception("Task error: %s", name)
            if self._on_task_error:
                self._on_task_error(name, exc)
            return None

    async def cancel_all(self, *, reason: str = "shutdown", timeout: float = 5.0) -> None:
        """Cancel all tracked tasks and wait for completion."""

        if not self._tasks:
            return

        self._logger.info("Cancelling %d tasks (%s)", len(self._tasks), reason)
        for task in list(self._tasks.values()):
            if task.done():
                continue
            task.cancel()

        await self._wait_for_tasks(self._tasks.values(), timeout=timeout)
        self._tasks.clear()

    async def cancel(self, name: str, *, timeout: float = 5.0) -> None:
        task = self._tasks.get(name)
        if not task:
            return
        if not task.done():
            task.cancel()
            await self._wait_for_tasks((task,), timeout=timeout)
        self._tasks.pop(name, None)

    async def _wait_for_tasks(self, tasks: Iterable[asyncio.Task[Any]], *, timeout: float) -> None:
        pending = {task for task in tasks if not task.done()}
        if not pending:
            return
        try:
            await asyncio.wait(pending, timeout=timeout)
        except Exception:  # pragma: no cover - defensive logging
            self._logger.debug("Error while waiting for tasks", exc_info=True)

    # ------------------------------------------------------------------
    # Introspection

    def active_names(self) -> list[str]:
        return list(self._tasks.keys())

    def active_count(self) -> int:
        return len(self._tasks)

    def shutdown_requested(self) -> bool:
        return self._shutdown_event.is_set()

    def request_shutdown(self) -> None:
        self._shutdown_event.set()
