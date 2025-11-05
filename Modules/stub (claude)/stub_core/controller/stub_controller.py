import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

from logger_core.commands import CommandMessage, StatusMessage, StatusType
from ..constants import DISPLAY_NAME
from ..model import StubModel, ModuleState

logger = logging.getLogger(__name__)


class StubController:
    def __init__(self, model: StubModel, shutdown_callback: Optional[callable] = None):
        self.model = model
        self._shutdown_callback = shutdown_callback
        self._shutdown_requested = False
        self._command_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        logger.info("StubController starting command listener")
        self._command_task = asyncio.create_task(self._handle_commands())

    async def stop(self) -> None:
        logger.info("StubController stopping")

        self._shutdown_requested = True

        if self._command_task and not self._command_task.done():
            self._command_task.cancel()
            try:
                await self._command_task
            except asyncio.CancelledError:
                pass

        logger.info("StubController stopped")

    async def _setup_stdin_reader(self) -> Optional[asyncio.StreamReader]:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        try:
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        except (PermissionError, NotImplementedError) as exc:
            logger.warning(f"Command listener disabled: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Failed to set up command listener: {exc}", exc_info=True)
            return None

        return reader

    async def _handle_commands(self) -> None:
        reader = await self._setup_stdin_reader()
        if not reader:
            logger.info("Command handler disabled (no stdin)")
            return

        logger.info("Command handler task started")

        while not self._shutdown_requested:
            try:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    logger.info("Parent closed stdin, initiating shutdown")
                    await self._initiate_shutdown("stdin closed")
                    break

                payload = line.decode().strip()
                if not payload:
                    continue

                command_data = CommandMessage.parse(payload)
                if not command_data:
                    continue

                await self._process_command(command_data)

            except Exception as e:
                logger.error(f"Command handler error: {e}", exc_info=True)

        logger.info("Command handler task ended")

    async def _process_command(self, command_data: Dict[str, Any]) -> None:
        command_type = command_data.get("command")
        logger.info(f"Received command: {command_type}")

        if command_type == "quit":
            await self._handle_quit()
        elif command_type == "get_status":
            await self._handle_get_status()
        elif command_type == "start_session":
            await self._handle_start_session(command_data)
        elif command_type == "start_recording":
            await self._handle_start_recording(command_data)
        elif command_type == "stop_recording":
            await self._handle_stop_recording()
        else:
            logger.warning(f"Unknown command: {command_type}")

    async def _handle_quit(self) -> None:
        logger.info("Quit command received, initiating shutdown")
        await self._initiate_shutdown("quit command")

    async def _handle_get_status(self) -> None:
        status = self.model.get_status_info()
        StatusMessage.send({
            "status": "ready",
            "state": status["state"],
            "recording": status["recording"],
        })
        logger.debug(f"Status sent: {status}")

    async def _handle_start_session(self, command_data: Dict[str, Any]) -> None:
        session_dir = command_data.get("session_dir")
        if session_dir:
            self.model.session_dir = Path(session_dir)
            logger.info(f"Session started: {session_dir}")

    async def _handle_start_recording(self, command_data: Dict[str, Any]) -> None:
        trial_number = command_data.get("trial_number", 1)
        self.model.trial_number = trial_number
        self.model.recording = True
        self.model.state = ModuleState.RECORDING

        logger.info(f"[STUB] Recording started: trial {trial_number}")

    async def _handle_stop_recording(self) -> None:
        self.model.recording = False
        self.model.state = ModuleState.IDLE

        logger.info("[STUB] Recording stopped")

    async def _initiate_shutdown(self, reason: str) -> None:
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

        if self._shutdown_callback:
            await self._shutdown_callback()
