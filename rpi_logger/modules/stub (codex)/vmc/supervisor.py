"""Supervisor coordinating the stub (codex) VMC stack."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .constants import DISPLAY_NAME, MODULE_ID
from .controller import StubCodexController
from .model import StubCodexModel
from .view import StubCodexView
from .runtime import ModuleRuntime, RuntimeContext, RuntimeFactory


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


@dataclass(slots=True)
class RuntimeRetryPolicy:
    """Retry behaviour when constructing the domain runtime."""

    interval: float = 3.0
    max_attempts: Optional[int] = None
    on_retry: Optional[LifecycleHook] = None
    on_failure: Optional[LifecycleHook] = None


class StubCodexSupervisor:
    """Owns model/controller/view lifecycle and orchestrates shutdown."""

    def __init__(
        self,
        args,
        module_dir: Path,
        logger: logging.Logger,
        hooks: Optional[LifecycleHooks] = None,
        retry_policy: Optional[RetryPolicy] = None,
        runtime_factory: Optional[RuntimeFactory] = None,
        runtime_retry_policy: Optional[RuntimeRetryPolicy] = None,
        display_name: Optional[str] = None,
        module_id: Optional[str] = None,
        view_factory: Optional[Callable[..., StubCodexView]] = None,
        view_kwargs: Optional[dict[str, Any]] = None,
        config_path: Optional[Path] = None,
    ) -> None:
        start = time.perf_counter()

        self.args = args
        self.logger = logger
        self.display_name = display_name or DISPLAY_NAME
        self.module_id = module_id or MODULE_ID
        self.hooks = hooks or LifecycleHooks()
        self.retry_policy = retry_policy
        self.runtime_factory = runtime_factory
        self.runtime_retry_policy = runtime_retry_policy
        self.module_dir = module_dir
        self._view_factory = view_factory or StubCodexView
        self._view_kwargs = dict(view_kwargs) if view_kwargs else {}
        explicit_config_path: Optional[Path]
        candidate = config_path or getattr(args, "config_path", None)
        if candidate:
            explicit_config_path = Path(candidate)
        else:
            explicit_config_path = None
        self.model = StubCodexModel(
            args,
            module_dir,
            display_name=self.display_name,
            module_id=self.module_id,
            config_path=explicit_config_path,
        )
        self.controller = StubCodexController(
            args,
            self.model,
            logger,
            display_name=self.display_name,
        )
        self.runtime: Optional[ModuleRuntime] = None
        self.view: Optional[StubCodexView] = None
        self._shutdown_in_progress = False
        self._view_runtime_ms: float = 0.0
        self._retry_task: Optional[asyncio.Task] = None
        self._device_missing = False
        self._runtime_attempts = 0

        self.model.apply_initial_window_geometry()

        if getattr(args, "mode", "gui") == "gui":
            try:
                view_kwargs = dict(self._view_kwargs)
                view_kwargs.setdefault("logger", self.logger.getChild("View"))
                self.view = self._view_factory(
                    args,
                    self.model,
                    action_callback=self.controller.handle_user_action,
                    display_name=self.display_name,
                    **view_kwargs,
                )
                self.logger.info("%s supervisor initialized in GUI mode", self.display_name)
            except Exception as exc:
                self.logger.warning("GUI unavailable (%s), falling back to headless mode", exc)
                self.view = None
        else:
            self.logger.info("%s supervisor initialized in headless mode", self.display_name)

        elapsed = (time.perf_counter() - start) * 1000.0
        self.logger.info("%s supervisor constructed in %.2f ms", self.display_name, elapsed)

    async def run(self) -> None:
        await self._run_hook(self.hooks.before_start, "before_start")
        await self.controller.start()

        if self.runtime_factory:
            await self._start_runtime()

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

        await self._stop_runtime(reason="supervisor_shutdown")

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
            self.display_name,
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

    # ------------------------------------------------------------------
    # Runtime management

    async def _start_runtime(self) -> None:
        if self.runtime_factory is None or self.runtime is not None:
            return

        retry_policy = self.runtime_retry_policy

        while not self.model.shutdown_event.is_set():
            self._runtime_attempts += 1
            attempt = self._runtime_attempts

            try:
                context = self._build_runtime_context()
                runtime = await self._call_runtime_factory(context)
                self.controller.attach_runtime(runtime)
                await runtime.start()
                self.runtime = runtime
                self._runtime_attempts = 0
                self.logger.info("Module runtime started (attempt %d)", attempt)
                return
            except Exception as exc:
                self.logger.exception("Runtime start attempt %d failed", attempt, exc_info=exc)
                self.controller.attach_runtime(None)

                if not retry_policy or not self._should_retry_runtime(attempt, retry_policy):
                    if retry_policy and retry_policy.on_failure:
                        await self._run_hook(retry_policy.on_failure, "runtime_failure")
                    raise

                await self._run_hook(retry_policy.on_retry, "runtime_retry")
                await self._sleep_with_shutdown_awareness(max(0.1, float(retry_policy.interval)))

        self.logger.warning("Runtime start aborted due to pending shutdown")

    async def _stop_runtime(self, *, reason: str) -> None:
        runtime = self.runtime
        if not runtime:
            return

        self.logger.info("Stopping module runtime (%s)", reason)

        try:
            await runtime.shutdown()
        except Exception:
            self.logger.exception("Runtime shutdown handler failed")

        try:
            await runtime.cleanup()
        except Exception:
            self.logger.exception("Runtime cleanup failed")

        self.controller.attach_runtime(None)
        self.runtime = None

    async def _call_runtime_factory(self, context: RuntimeContext) -> ModuleRuntime:
        result = self.runtime_factory(context)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ModuleRuntime):
            missing = [
                name
                for name in ("start", "shutdown", "cleanup")
                if not hasattr(result, name)
            ]
            if missing:
                raise TypeError(
                    "Runtime factory must return an object implementing %s; got %r"
                    % (", ".join(missing), type(result)),
                )
        return result  # type: ignore[return-value]

    def _build_runtime_context(self) -> RuntimeContext:
        return RuntimeContext(
            args=self.args,
            module_dir=self.module_dir,
            logger=self.logger,
            model=self.model,
            controller=self.controller,
            supervisor=self,
            view=self.view,
            display_name=self.display_name,
            module_id=self.module_id,
        )

    def _should_retry_runtime(self, attempt: int, policy: RuntimeRetryPolicy) -> bool:
        max_attempts = policy.max_attempts
        if max_attempts is not None and attempt >= max_attempts:
            self.logger.error(
                "Runtime failed after %d attempt(s); aborting",
                attempt,
            )
            return False
        return True

    async def _sleep_with_shutdown_awareness(self, interval: float) -> None:
        try:
            await asyncio.wait_for(self.model.shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            return
