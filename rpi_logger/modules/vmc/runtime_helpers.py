"""Shared helper utilities for runtimes hosted by the stub supervisor."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Optional, Set

from rpi_logger.core.logging_utils import get_module_logger


class BackgroundTaskManager:
    """Track background tasks spawned by a runtime and cancel them safely."""

    def __init__(self, name: str = "StubBackgroundTasks", logger: Optional[logging.Logger] = None) -> None:
        self._name = name
        self._logger = logger or get_module_logger(name)
        self._tasks: Set[asyncio.Task] = set()
        self._closing = False

    def create(self, coro: Awaitable, *, name: Optional[str] = None) -> asyncio.Task:
        if self._closing:
            raise RuntimeError(f"{self._name} is closing; refusing to create new tasks")
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro, name=name or getattr(coro, "__name__", None))
        self._register(task)
        return task

    def add(self, task: asyncio.Task) -> asyncio.Task:
        if task.done():
            return task
        self._register(task)
        return task

    def _register(self, task: asyncio.Task) -> None:
        self._tasks.add(task)

        def _on_done(t: asyncio.Task) -> None:
            self._tasks.discard(t)
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                exc = None
            except Exception as err:  # pragma: no cover - defensive logging
                self._logger.exception("%s failed extracting task exception", self._name, exc_info=err)
                return
            if exc:
                self._logger.error("%s task %s failed: %s", self._name, t.get_name(), exc, exc_info=exc)

        task.add_done_callback(_on_done)

    async def shutdown(self, *, timeout: float = 5.0) -> bool:
        self._closing = True
        pending = [task for task in self._tasks if not task.done()]
        if not pending:
            return True
        for task in pending:
            task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            still_pending = [t.get_name() or f"Task@{id(t):x}" for t in pending if not t.done()]
            self._logger.warning(
                "%s timeout cancelling %d task(s): %s",
                self._name,
                len(still_pending),
                ", ".join(still_pending),
            )
            return False

    def active(self) -> int:
        return sum(1 for task in self._tasks if not task.done())


class ShutdownGuard:
    """Abort the process if cleanup takes too long."""

    def __init__(self, logger: Optional[logging.Logger] = None, *, timeout: float = 15.0, exit_code: int = 101) -> None:
        self._logger = logger or get_module_logger("StubShutdownGuard")
        self._timeout = max(0.5, float(timeout))
        self._exit_code = exit_code
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._guard_loop(), name="StubShutdownGuard")

    async def cancel(self) -> None:
        task = self._task
        if not task:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _guard_loop(self) -> None:
        try:
            await asyncio.sleep(self._timeout)
        except asyncio.CancelledError:  # pragma: no cover - normal cancellation path
            return
        self._logger.error("Shutdown guard triggered after %.1fs; forcing exit", self._timeout)
        os._exit(self._exit_code)
