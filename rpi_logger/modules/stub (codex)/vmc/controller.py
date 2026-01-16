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

from rpi_logger.core.commands import CommandMessage, StatusMessage, StatusType

from .constants import DISPLAY_NAME
from .model import StubCodexModel
from .runtime import ModuleRuntime


class StubCodexController:
    """Coordinates domain logic and command handling."""

    def __init__(
        self,
        args,
        model: StubCodexModel,
        module_logger: logging.Logger,
        *,
        display_name: str = DISPLAY_NAME,
    ) -> None:
        self.args = args
        self.model = model
        self.logger = module_logger
        self.display_name = display_name
        self._command_task: Optional[asyncio.Task] = None
        self._stdin_shutdown = threading.Event()
        self._shutdown_requested = False
        self._runtime: Optional[ModuleRuntime] = None

    async def start(self) -> None:
        await self.model.prepare_environment(self.logger)

        self.logger.debug("%s module initializing", self.display_name)
        StatusMessage.send(StatusType.INITIALIZING, {"message": f"{self.display_name} starting"})
        await asyncio.sleep(0)

        ready_ms = self.model.mark_ready()
        self.logger.info("%s module ready and idle (%.1f ms)", self.display_name, ready_ms)

        # Skip command listener if not enabled, but allow standalone test mode
        test_camera_index = getattr(self.args, "camera_index", None)
        if not self.args.enable_commands and test_camera_index is None:
            self.logger.info("Command channel disabled; initiating shutdown")
            await self._begin_shutdown("commands disabled")
            return

        # If camera_index is provided, defer command listener until after camera init
        # This prevents stdin reading from interfering with libcamera initialization
        if test_camera_index is not None:
            self.logger.debug("Deferring command listener start (camera init via --camera-index)")
            return

        # Start command listener if commands are enabled
        if self.args.enable_commands:
            self._command_task = asyncio.create_task(self._listen_for_commands(), name="StubCodexCommands")

    async def stop(self) -> None:
        self._shutdown_requested = True

        if self._command_task and not self._command_task.done():
            self._command_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._command_task

        self._stdin_shutdown.set()

        StatusMessage.send(StatusType.QUITTING, {"message": f"{self.display_name} exiting"})
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
        """Listen for commands from stdin using platform-appropriate polling.

        On Linux/macOS: Uses select.select() to poll stdin without modifying
        its file descriptor state. This avoids interference with libcamera's
        internal threading that was caused by asyncio's connect_read_pipe()
        setting stdin to non-blocking.

        On Windows: select.select() doesn't work with file handles (only sockets),
        so we use blocking read in a thread. For piped stdin (subprocess mode),
        this works because the parent process sends commands that unblock the read.
        """
        is_windows = sys.platform == "win32"

        if is_windows:
            # On Windows, we can't use select() on stdin.
            # For subprocess mode (piped stdin), blocking readline is fine since
            # the parent will send commands that unblock the read.
            def read_stdin_line() -> str:
                """Blocking read of one line from stdin."""
                try:
                    return sys.stdin.readline()
                except Exception:
                    return ""

            try:
                while not self.model.shutdown_event.is_set():
                    # Run blocking readline in a thread so we don't block the event loop
                    line = await asyncio.to_thread(read_stdin_line)

                    if line == "":
                        # EOF - stdin was closed
                        break
                    if not line.strip():
                        continue

                    command = CommandMessage.parse(line)
                    if not command:
                        self.logger.debug("Failed to parse command: %s", line[:100])
                        continue

                    self.logger.debug("Received command: %s", command.get("command", "unknown"))
                    await self._process_command(command)
            finally:
                self._stdin_shutdown.set()
        else:
            # On Unix, use select-based polling
            import select

            def poll_stdin_line(timeout: float = 0.2) -> Optional[str]:
                """Poll stdin using select and read one line if available."""
                try:
                    readable, _, _ = select.select([sys.stdin], [], [], timeout)
                    if not readable:
                        return None
                    return sys.stdin.readline()
                except Exception:
                    return ""

            try:
                while not self.model.shutdown_event.is_set():
                    line = await asyncio.to_thread(poll_stdin_line, 0.2)

                    if line is None:
                        continue
                    if line == "":
                        break
                    if not line.strip():
                        continue

                    command = CommandMessage.parse(line)
                    if not command:
                        self.logger.debug("Failed to parse command: %s", line[:100])
                        continue

                    self.logger.debug("Received command: %s", command.get("command", "unknown"))
                    await self._process_command(command)
            finally:
                self._stdin_shutdown.set()

    async def request_shutdown(self, reason: str) -> None:
        await self._begin_shutdown(reason)

    async def _process_command(self, command: Dict[str, Any]) -> None:
        action = (command.get("command") or "").lower()

        # Normalize legacy logger commands to the runtime's canonical verbs so
        # modules launched through the master controller continue to function.
        legacy_aliases = {
            "record": "start_recording",
            "start_record": "start_recording",
            "pause": "stop_recording",
            "stop_record": "stop_recording",
        }
        canonical = legacy_aliases.get(action)
        if canonical:
            command = dict(command)
            command["command"] = canonical
            action = canonical

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
        elif action == "stop_session":
            await self._handle_stop_session()
            handled = True
        elif action == "start_recording":
            await self._handle_start_recording(command)
            await self._forward_to_runtime(command)
            handled = True
        elif action == "stop_recording":
            await self._handle_stop_recording()
            await self._forward_to_runtime(command)
            handled = True

        if not handled and self._runtime:
            self.logger.debug("Forwarding command to runtime: %s", action)
            try:
                handled = await self._runtime.handle_command(command)
                self.logger.debug("Runtime handled command %s: %s", action, handled)
            except Exception:
                self.logger.exception("Runtime command handler failed [%s]", action)
                handled = True
        elif not handled:
            self.logger.warning("No runtime attached to handle command: %s", action)

        if not handled:
            self.logger.warning("Unknown command: %s", action)

    async def _handle_start_session(self, command: Dict[str, Any]) -> None:
        session_dir = command.get("session_dir")
        if not session_dir:
            return
        path = Path(session_dir)
        self.model.session_dir = path
        self.logger.debug("Session directory set to %s", path)
        runtime = self._runtime
        if runtime and hasattr(runtime, "on_session_dir_available"):
            try:
                await runtime.on_session_dir_available(path)
            except Exception:
                self.logger.exception("Runtime session-dir handler failed")

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

    async def _handle_stop_session(self) -> None:
        await self._handle_stop_recording()
        if self.model.session_dir is not None:
            self.logger.debug("Session directory cleared (stop_session command)")
        self.model.session_dir = None

    async def _forward_to_runtime(self, command: Dict[str, Any]) -> bool:
        runtime = self._runtime
        if not runtime:
            return False
        try:
            return await runtime.handle_command(command)
        except Exception:
            self.logger.exception("Runtime command handler failed [%s]", command.get("command"))
            return True

    def _send_status_report(self, source: str) -> None:
        payload = self.model.get_status_snapshot()
        payload["source"] = source
        StatusMessage.send(StatusType.STATUS_REPORT, payload)

    async def _begin_shutdown(self, reason: str) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True

        now_ms = (time.perf_counter() - self.model.startup_timestamp) * 1000.0
        StatusMessage.send(StatusType.SHUTDOWN_STARTED, {"message": f"{self.display_name}: {reason}"})
        StatusMessage.send(
            StatusType.STATUS_REPORT,
            {"event": "shutdown_requested", "runtime_ms": round(now_ms, 1)},
        )
        self.model.request_shutdown(reason)

    def attach_runtime(self, runtime: Optional[ModuleRuntime]) -> None:
        """Allow the supervisor to register a runtime for command dispatch."""
        self._runtime = runtime

    async def start_command_listener(self) -> None:
        """Start the command listener (call from runtime after camera init).

        This is used when --camera-index is provided to defer stdin reading
        until after libcamera initialization completes. The runtime calls
        this after camera is initialized and frames are flowing.
        """
        if self._command_task is not None:
            self.logger.debug("Command listener already started")
            return

        if not self.args.enable_commands:
            self.logger.debug("Commands not enabled, skipping listener start")
            return

        self.logger.debug("Starting deferred command listener (camera init complete)")
        self._command_task = asyncio.create_task(
            self._listen_for_commands(), name="StubCodexCommands"
        )
