"""VOG headless mode for parent-controlled sessions."""

from __future__ import annotations
import asyncio
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, Dict, Any

from rpi_logger.modules.base.modes.base_mode import BaseMode
from rpi_logger.core.commands import CommandMessage, StatusMessage

from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..vog_system import VOGSystem


class SimpleMode(BaseMode):
    """Headless mode for parent-controlled VOG sessions."""

    def __init__(self, system: "VOGSystem", enable_commands: bool = False):
        super().__init__(system)
        self.enable_commands = enable_commands
        self.command_handler: CommandHandler | None = None
        self._command_task: asyncio.Task | None = None

    async def run(self) -> None:
        """Run the headless mode main loop."""
        self.system.running = True

        if self.enable_commands:
            reader = await self._setup_stdin_reader()
            if reader is None:
                self.logger.warning(
                    "Parent command interface unavailable; waiting for shutdown signal",
                )
            else:
                self.command_handler = CommandHandler(self.system, gui=None)
                self._command_task = asyncio.create_task(self._command_listener(reader))

        try:
            while self.is_running():
                await asyncio.sleep(0.1)
        finally:
            if self._command_task:
                self._command_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._command_task

    async def on_device_connected(self, port: str) -> None:
        """Handle device connection event."""
        StatusMessage.send("device_connected", {"port": port})

    async def on_device_disconnected(self, port: str) -> None:
        """Handle device disconnection event."""
        StatusMessage.send("device_disconnected", {"port": port})

    async def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]) -> None:
        """Handle data received from device."""
        # In headless mode, data is logged by handler but we can notify parent
        if data_type == 'data':
            StatusMessage.send("vog_data", {
                "port": port,
                "trial_number": data.get('trial_number'),
                "shutter_open": data.get('shutter_open'),
                "shutter_closed": data.get('shutter_closed'),
            })

    async def _setup_stdin_reader(self) -> asyncio.StreamReader | None:
        """Set up stdin reader for parent commands."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        try:
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        except (PermissionError, NotImplementedError) as exc:
            self.logger.warning("Command listener disabled: %s", exc)
            return None
        except Exception as exc:
            self.logger.error("Failed to set up command listener: %s", exc, exc_info=True)
            return None

        return reader

    async def _command_listener(self, reader: asyncio.StreamReader) -> None:
        """Listen for commands from parent process via stdin."""
        if not self.command_handler:
            return

        self.logger.info("Command listener started (headless parent mode)")

        while self.is_running():
            try:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    self.logger.info("Parent closed stdin, initiating shutdown")
                    self.system.running = False
                    self.system.shutdown_event.set()
                    break

                payload = line.decode().strip()
                if not payload:
                    continue

                command_data = CommandMessage.parse(payload)
                if not command_data:
                    StatusMessage.send("error", {"message": "Invalid JSON"})
                    continue

                continue_running = await self.command_handler.handle_command(command_data)
                if not continue_running:
                    self.logger.info("Quit command received, shutting down")
                    self.system.running = False
                    self.system.shutdown_event.set()
                    break

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                StatusMessage.send("error", {"message": f"Command error: {exc}"})
                self.logger.error("Command listener error: %s", exc, exc_info=True)
                break

        self.logger.info("Command listener stopped")
