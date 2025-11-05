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


@dataclass(slots=True)
class RetryPolicy:
    """Configuration for asynchronous device retry monitoring."""

    check: Callable[["StubCodexSupervisor"], Awaitable[bool] | bool]
    check_interval: float = 3.0
    on_missing: Optional[LifecycleHook] = None
    on_recovered: Optional[LifecycleHook] = None


class StubCodexSupervisor:
    """Owns model/controller/view lifecycle and orchestrates shutdown."""

    def __init__(
        self,
        args,
        module_dir: Path,
        logger: logging.Logger,
        hooks: Optional[LifecycleHooks] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        start = time.perf_counter()

        self.args = args
        self.logger = logger
        self.hooks = hooks or LifecycleHooks()
        self.retry_policy = retry_policy
        self.model = StubCodexModel(args, module_dir)
        self.controller = StubCodexController(args, self.model, logger)
        self.view: Optional[StubCodexView] = None
        self._shutdown_in_progress = False
        self._view_runtime_ms: float = 0.0
        self._retry_task: Optional[asyncio.Task] = None
        self._device_missing = False

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

        self._start_retry_monitor()

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

        await self._stop_retry_monitor()

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

    def _start_retry_monitor(self) -> None:
        if not self.retry_policy or self._retry_task:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.logger.warning("Retry monitor unavailable: event loop missing")
            return
        self._retry_task = loop.create_task(self._run_retry_loop(), name="StubCodexRetryMonitor")

    async def _stop_retry_monitor(self) -> None:
        task = self._retry_task
        if not task:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._retry_task = None
        self._device_missing = False

    async def _run_retry_loop(self) -> None:
        policy = self.retry_policy
        if not policy:
            return
        interval = max(0.2, float(policy.check_interval))
        while not self.model.shutdown_event.is_set():
            healthy = await self._evaluate_retry_check(policy)
            if healthy:
                if self._device_missing:
                    self.logger.info("Device recovered; resuming normal operation")
                    await self._run_hook(policy.on_recovered, "retry_on_recovered")
                    self._device_missing = False
            else:
                if not self._device_missing:
                    self._device_missing = True
                    self.logger.warning("Device check failed; entering retry state")
                    await self._run_hook(policy.on_missing, "retry_on_missing")
            try:
                await asyncio.wait_for(self.model.shutdown_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
        self._device_missing = False

    async def _evaluate_retry_check(self, policy: RetryPolicy) -> bool:
        try:
            result = policy.check(self)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception:
            self.logger.exception("Retry check raised an exception")
            return False
