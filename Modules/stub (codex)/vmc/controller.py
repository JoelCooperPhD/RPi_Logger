"""Controller component orchestrating the stub (codex) module."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from logger_core.commands import CommandMessage, StatusMessage, StatusType

from .constants import DISPLAY_NAME
from .model import StubCodexModel
from .runtime import ModuleRuntime


class StubCodexController:
    """Coordinates domain logic and command handling."""

    def __init__(self, args, model: StubCodexModel, module_logger: logging.Logger) -> None:
        self.args = args
        self.model = model
        self.logger = module_logger
        self._command_task: Optional[asyncio.Task] = None
        self._stdin_thread: Optional[threading.Thread] = None
        self._stdin_shutdown = threading.Event()
        self._command_queue: Optional[asyncio.Queue[str]] = None
        self._shutdown_requested = False
        self._runtime: Optional[ModuleRuntime] = None

    async def start(self) -> None:
        await self.model.prepare_environment(self.logger)

        self.logger.info("%s module initializing", DISPLAY_NAME)
        StatusMessage.send(StatusType.INITIALIZING, {"message": f"{DISPLAY_NAME} starting"})
        await asyncio.sleep(0)

        ready_ms = self.model.mark_ready()
        self.logger.info("%s module ready and idle (%.1f ms)", DISPLAY_NAME, ready_ms)

        if not self.args.enable_commands:
            self.logger.warning("Command channel disabled; initiating shutdown")
            await self._begin_shutdown("commands disabled")
            return

        self._command_task = asyncio.create_task(self._listen_for_commands(), name="StubCodexCommands")

    async def stop(self) -> None:
        self._shutdown_requested = True

        if self._command_task and not self._command_task.done():
            self._command_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._command_task

        self._stdin_shutdown.set()
        if self._command_queue:
            try:
                self._command_queue.put_nowait("")
            except asyncio.QueueFull:
                pass

        StatusMessage.send(StatusType.QUITTING, {"message": f"{DISPLAY_NAME} exiting"})
        await asyncio.sleep(0.05)

    async def handle_user_action(self, action: str, **kwargs: Any) -> None:
        action = action or ""
        handled = False
        if action == "start_recording":
            await self._handle_start_recording(kwargs)
            handled = True
        elif action == "stop_recording":
            await self._handle_stop_recording()
            handled = True
        elif action == "quit":
            await self._begin_shutdown("quit requested from view")
            handled = True
        elif action == "start_session":
            await self._handle_start_session(kwargs)
            handled = True
        elif action == "get_status":
            self._send_status_report("user_action")
            handled = True

        if not handled and self._runtime:
            try:
                handled = await self._runtime.handle_user_action(action, **kwargs)
            except Exception:
                self.logger.exception("Runtime user action handler failed [%s]", action)
                handled = True

        if not handled:
            self.logger.debug("Unhandled user action: %s", action)

    async def _listen_for_commands(self) -> None:
        """Listen for commands from stdin in a background thread."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._command_queue = queue
        shutdown_flag = self._stdin_shutdown

        def reader() -> None:
            try:
                while not shutdown_flag.is_set():
                    line = sys.stdin.readline()
                    if not line:
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, line)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, "")

        try:
            thread = threading.Thread(target=reader, name="StubCodexCommandReader", daemon=True)
            thread.start()
            self._stdin_thread = thread
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("Command reader unavailable: %s", exc)
            return

        try:
            while not self.model.shutdown_event.is_set():
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    continue

                command = CommandMessage.parse(line)
                if not command:
                    continue

                await self._process_command(command)
        finally:
            shutdown_flag.set()
            if self._stdin_thread:
                self._stdin_thread.join(timeout=0.5)
                self._stdin_thread = None

    async def request_shutdown(self, reason: str) -> None:
        await self._begin_shutdown(reason)

    async def _process_command(self, command: Dict[str, Any]) -> None:
        action = (command.get("command") or "").lower()
        handled = False
        if action == "quit":
            self.logger.info("Received quit command from controller")
            await self._begin_shutdown("quit command received")
            handled = True
        elif action == "get_status":
            self._send_status_report("command")
            handled = True
        elif action == "start_session":
            await self._handle_start_session(command)
            handled = True
        elif action == "start_recording":
            await self._handle_start_recording(command)
            handled = True
        elif action == "stop_recording":
            await self._handle_stop_recording()
            handled = True

        if not handled and self._runtime:
            try:
                handled = await self._runtime.handle_command(command)
            except Exception:
                self.logger.exception("Runtime command handler failed [%s]", action)
                handled = True

        if not handled:
            self.logger.warning("Unknown command: %s", action)

    async def _handle_start_session(self, command: Dict[str, Any]) -> None:
        session_dir = command.get("session_dir")
        if not session_dir:
            return
        path = Path(session_dir)
        self.model.session_dir = path
        self.logger.info("Session directory set to %s", path)

    async def _handle_start_recording(self, command: Dict[str, Any]) -> None:
        trial_number = int(command.get("trial_number", 1))
        self.model.trial_number = trial_number
        self.model.recording = True
        self.logger.info("Recording started (trial %s)", trial_number)
        self._send_status_report("recording_started")

    async def _handle_stop_recording(self) -> None:
        if not self.model.recording:
            return
        self.model.recording = False
        self.logger.info("Recording stopped")
        self._send_status_report("recording_stopped")

    def _send_status_report(self, source: str) -> None:
        payload = self.model.get_status_snapshot()
        payload["source"] = source
        StatusMessage.send(StatusType.STATUS_REPORT, payload)

    async def _begin_shutdown(self, reason: str) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True

        now_ms = (time.perf_counter() - self.model.startup_timestamp) * 1000.0
        StatusMessage.send(StatusType.SHUTDOWN_STARTED, {"message": f"{DISPLAY_NAME}: {reason}"})
        StatusMessage.send(
            StatusType.STATUS_REPORT,
            {"event": "shutdown_requested", "runtime_ms": round(now_ms, 1)},
        )
        self.model.request_shutdown(reason)

    def attach_runtime(self, runtime: Optional[ModuleRuntime]) -> None:
        """Allow the supervisor to register a runtime for command dispatch."""
        self._runtime = runtime
