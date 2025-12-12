"""Asyncio helpers for safer long-running operation."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Awaitable, Optional

from .logging_utils import LoggerLike, ensure_structured_logger


def _task_label(task: asyncio.Task[Any], context: Optional[str]) -> str:
    if context:
        return context
    if hasattr(task, "get_name"):
        try:
            name = task.get_name()
        except Exception:  # pragma: no cover - defensive
            name = None
        if name:
            return name
    return "background task"


def add_task_exception_logger(
    task: asyncio.Task[Any],
    *,
    logger: LoggerLike = None,
    context: Optional[str] = None,
) -> asyncio.Task[Any]:
    """Ensure task exceptions are retrieved and logged.

    Without this, exceptions in fire-and-forget tasks can surface as
    "Task exception was never retrieved" warnings (often long after the
    original failure) and can spam logs during long runs.
    """
    task_logger = ensure_structured_logger(logger, fallback_name="asyncio")

    def _done(done_task: asyncio.Task[Any]) -> None:
        try:
            done_task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            task_logger.exception(
                "Unhandled exception in %s",
                _task_label(done_task, context),
            )

    task.add_done_callback(_done)
    return task


def create_logged_task(
    coro: Awaitable[Any],
    *,
    logger: LoggerLike = None,
    context: Optional[str] = None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
    pending: Optional[set[asyncio.Task[Any]]] = None,
) -> asyncio.Task[Any]:
    """Create a task that won't lose exceptions, optionally tracking it."""
    if loop is None:
        loop = asyncio.get_running_loop()

    task = loop.create_task(coro)
    if context and hasattr(task, "set_name"):
        with contextlib.suppress(Exception):  # pragma: no cover - best effort
            task.set_name(context)

    add_task_exception_logger(task, logger=logger, context=context)

    if pending is not None:
        pending.add(task)
        task.add_done_callback(pending.discard)

    return task
