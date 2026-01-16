"""Utilities for tracking and cancelling background asyncio tasks."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger


@dataclass(slots=True)
class _TaskRecord:
    task: asyncio.Task
    name: str
    created: float
    done_callback: Optional[Callable[[asyncio.Task], None]]


class AsyncTaskManager:
    """Keep track of asynchronously spawned tasks and shut them down safely."""

    def __init__(
        self,
        name: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._name = name or self.__class__.__name__
        self._logger = logger or get_module_logger(self._name)
        self._closed = False
        self._records: dict[asyncio.Task, _TaskRecord] = {}
        self._name_index: dict[str, set[asyncio.Task]] = defaultdict(set)

    # ------------------------------------------------------------------
    # task registration helpers
    # ------------------------------------------------------------------
    def create(
        self,
        coro: Awaitable,
        *,
        name: Optional[str] = None,
        done_callback: Optional[Callable[[asyncio.Task], None]] = None,
    ) -> asyncio.Task:
        """Create and register a task on the current running loop."""

        if self._closed:
            raise RuntimeError(f"{self._name} is shutting down; no new tasks permitted")

        loop = asyncio.get_running_loop()
        task_name = name or getattr(coro, "__name__", None) or repr(coro)
        task = loop.create_task(coro, name=task_name)
        self._register(task, task_name, done_callback)
        return task

    def add(
        self,
        task: asyncio.Task,
        *,
        name: Optional[str] = None,
        done_callback: Optional[Callable[[asyncio.Task], None]] = None,
    ) -> asyncio.Task:
        """Register an existing task that was created elsewhere."""

        if task.done():
            # Nothing to track; log unexpected errors immediately.
            self._log_task_result(task, context=name or task.get_name())
            return task

        task_name = name or task.get_name() or f"Task@{id(task):x}"
        self._register(task, task_name, done_callback)
        return task

    def _register(
        self,
        task: asyncio.Task,
        name: str,
        done_callback: Optional[Callable[[asyncio.Task], None]] = None,
    ) -> None:
        record = _TaskRecord(task=task, name=name, created=time.perf_counter(), done_callback=done_callback)
        self._records[task] = record
        self._name_index[name].add(task)

        def _finalizer(t: asyncio.Task) -> None:
            rec = self._records.pop(t, None)
            if rec:
                self._name_index[rec.name].discard(t)
                if not self._name_index[rec.name]:
                    self._name_index.pop(rec.name, None)
            status = self._log_task_result(t, context=rec.name if rec else None)
            if rec:
                elapsed_ms = (time.perf_counter() - rec.created) * 1000
            else:
                elapsed_ms = 0.0
            self._logger.debug(
                "%s task %s finished (%s) in %.1fms",
                self._name,
                (rec.name if rec else t.get_name() or f"Task@{id(t):x}"),
                status,
                elapsed_ms,
            )
            if rec and rec.done_callback is not None:
                try:
                    rec.done_callback(t)
                except Exception:  # pragma: no cover - defensive logging only
                    self._logger.exception("%s done callback failed", self._name)

        task.add_done_callback(_finalizer)

    # ------------------------------------------------------------------
    # task shutdown helpers
    # ------------------------------------------------------------------
    async def shutdown(self, *, timeout: float = 5.0) -> bool:
        """Cancel outstanding tasks and wait for their completion."""

        self._closed = True

        pending = [task for task in self._records if not task.done()]
        if not pending:
            return True

        return await self._cancel_and_wait(pending, timeout=timeout, reason="shutdown")

    async def cancel(self, name: str, *, timeout: float = 5.0) -> bool:
        """Cancel all tasks registered under a specific name."""

        tasks = list(self._name_index.get(name, ()))
        if not tasks:
            return True

        return await self._cancel_and_wait(tasks, timeout=timeout, reason=f"cancel:{name}")

    async def cancel_matching(self, names: Iterable[str], *, timeout: float = 5.0) -> bool:
        """Cancel all tasks whose registered name is in *names*."""

        names_list = list(names)
        to_cancel: list[asyncio.Task] = []
        for name in names_list:
            to_cancel.extend(self._name_index.get(name, ()))

        if not to_cancel:
            return True

        return await self._cancel_and_wait(to_cancel, timeout=timeout, reason="cancel_matching")

    async def _cancel_and_wait(
        self,
        tasks: Iterable[asyncio.Task],
        *,
        timeout: float,
        reason: str,
    ) -> bool:
        pending = [task for task in tasks if not task.done()]
        for task in pending:
            task.cancel()

        if not pending:
            return True

        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            hanging_names = []
            for task in pending:
                if task.done():
                    continue
                rec = self._records.get(task)
                hanging_names.append(rec.name if rec else task.get_name())
            self._logger.warning(
                "%s %s timed out after %.1fs; %d task(s) still pending: %s",
                self._name,
                reason,
                timeout,
                len(hanging_names),
                ", ".join(n for n in hanging_names if n),
            )
            return False

    # ------------------------------------------------------------------
    # inspection helpers
    # ------------------------------------------------------------------
    def active_count(self) -> int:
        return sum(1 for task in self._records if not task.done())

    def active_names(self) -> list[str]:
        """Return the list of task names that are still active."""

        return [rec.name for rec in self._records.values() if not rec.task.done()]

    def describe(self) -> list[dict[str, object]]:
        """Diagnostic snapshot of tracked tasks."""

        snapshot = []
        now = time.perf_counter()
        for rec in self._records.values():
            snapshot.append(
                {
                    "name": rec.name,
                    "done": rec.task.done(),
                    "created_ms": (now - rec.created) * 1000,
                    "cancelled": rec.task.cancelled(),
                }
            )
        return snapshot

    def _log_task_result(self, task: asyncio.Task, *, context: Optional[str]) -> str:
        if task.cancelled():
            return "cancelled"

        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return "cancelled"
        except Exception:  # pragma: no cover - extremely defensive
            self._logger.exception("%s: failed retrieving task exception", self._name)
            return "error:unknown"

        if exc is not None:
            self._logger.error(
                "%s task %s failed: %s",
                self._name,
                context or task.get_name(),
                exc,
                exc_info=True,
            )
            return f"error:{exc.__class__.__name__}"

        return "completed"


__all__ = ["AsyncTaskManager"]
