"""Supervisor coordinating the stub (codex) VMC stack."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .constants import DISPLAY_NAME
from .controller import StubCodexController
from .model import StubCodexModel
from .view import StubCodexView


LifecycleHook = Callable[["StubCodexSupervisor"], Optional[Awaitable[None]]]


@dataclass(slots=True)
class LifecycleHooks:
    """Optional async-aware callbacks triggered around the supervisor lifecycle."""

    before_start: Optional[LifecycleHook] = None
    after_start: Optional[LifecycleHook] = None
    before_shutdown: Optional[LifecycleHook] = None
    after_shutdown: Optional[LifecycleHook] = None


class StubCodexSupervisor:
    """Owns model/controller/view lifecycle and orchestrates shutdown."""

    def __init__(
        self,
        args,
        module_dir: Path,
        logger: logging.Logger,
        hooks: Optional[LifecycleHooks] = None,
    ) -> None:
        start = time.perf_counter()

        self.args = args
        self.logger = logger
        self.hooks = hooks or LifecycleHooks()
        self.model = StubCodexModel(args, module_dir)
        self.controller = StubCodexController(args, self.model, logger)
        self.view: Optional[StubCodexView] = None
        self._shutdown_in_progress = False
        self._view_runtime_ms: float = 0.0

        self.model.apply_initial_window_geometry()

        if getattr(args, "mode", "gui") == "gui":
            try:
                self.view = StubCodexView(args, self.model, action_callback=self.controller.handle_user_action)
                self.logger.info("StubCodexSupervisor initialized in GUI mode")
            except Exception as exc:
                self.logger.warning("GUI unavailable (%s), falling back to headless mode", exc)
                self.view = None
        else:
            self.logger.info("StubCodexSupervisor initialized in headless mode")

        elapsed = (time.perf_counter() - start) * 1000.0
        self.logger.info("StubCodexSupervisor constructed in %.2f ms", elapsed)

    async def run(self) -> None:
        await self._run_hook(self.hooks.before_start, "before_start")
        await self.controller.start()

        if self.view:
            self.view.attach_logging_handler()

        await self._run_hook(self.hooks.after_start, "after_start")

        tasks: list[asyncio.Task] = []
        shutdown_wait = asyncio.create_task(self.model.shutdown_event.wait(), name="StubCodexShutdownEvent")
        tasks.append(shutdown_wait)

        view_task: Optional[asyncio.Task] = None
        if self.view:
            view_task = asyncio.create_task(self.view.run(), name="StubCodexView")
            tasks.append(view_task)

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        if view_task and view_task in done:
            with contextlib.suppress(Exception):
                self._view_runtime_ms = view_task.result() or 0.0

        await self.shutdown()

        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def shutdown(self) -> None:
        if self._shutdown_in_progress:
            return
        self._shutdown_in_progress = True

        await self._run_hook(self.hooks.before_shutdown, "before_shutdown")

        await self.controller.stop()

        if self.view:
            await self.view.cleanup()
            if self._view_runtime_ms <= 0.0:
                self._view_runtime_ms = self.view.window_duration_ms

        await self.model.persist_window_geometry()

        self.model.record_window_duration(self._view_runtime_ms)
        self.model.finalize_metrics()
        metrics = self.model.metrics
        self.logger.info(
            "%s module stopped (runtime %.1f ms | shutdown %.1f ms | window %.1f ms)",
            DISPLAY_NAME,
            metrics.runtime_ms,
            metrics.shutdown_ms,
            metrics.window_ms,
        )

        self.model.send_runtime_report()
        self.model.emit_shutdown_logs(self.logger)

        await self._run_hook(self.hooks.after_shutdown, "after_shutdown")

    async def request_shutdown(self, reason: str) -> None:
        await self.controller.request_shutdown(reason)

    async def _run_hook(self, hook: Optional[LifecycleHook], stage: str) -> None:
        if not hook:
            return
        try:
            result = hook(self)
            if inspect.isawaitable(result):
                await result
        except Exception:
            self.logger.exception("Lifecycle hook '%s' failed", stage)
