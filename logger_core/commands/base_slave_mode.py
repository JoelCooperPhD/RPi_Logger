
import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Optional

from .command_protocol import CommandMessage, StatusMessage
from .base_handler import BaseCommandHandler


class BaseSlaveMode(ABC):

    def __init__(self, system: Any):
        self.system = system
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self._stdin_reader: Optional[asyncio.StreamReader] = None
        self._command_queue: asyncio.Queue = asyncio.Queue(maxsize=100)  # Bounded queue
        self._shutdown_event = asyncio.Event()

    @abstractmethod
    def create_command_handler(self) -> BaseCommandHandler:
        pass

    async def run(self) -> None:
        self.logger.info("Starting slave mode (optimized asyncio)")

        if hasattr(self.system, 'running'):
            self.system.running = True

        command_handler = self.create_command_handler()

        try:
            await self._setup_stdin_reader()
        except Exception as e:
            self.logger.error("Failed to setup stdin reader: %s", e)
            StatusMessage.send("error", {"message": f"Failed to setup stdin: {e}"})
            return

        await self._on_ready()

        try:
            await asyncio.gather(
                self._stdin_reader_loop(),
                self._command_processor_loop(command_handler),
                self._main_loop(),  # Module-specific main loop
                return_exceptions=True
            )
        except Exception as e:
            self.logger.error("Error in slave mode: %s", e, exc_info=True)
        finally:
            await self._on_shutdown()

        self.logger.info("Slave mode ended")

    async def _setup_stdin_reader(self) -> None:
        loop = asyncio.get_running_loop()
        self._stdin_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._stdin_reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        self.logger.debug("stdin reader configured")

    async def _stdin_reader_loop(self) -> None:
        if not self._stdin_reader:
            self.logger.error("stdin reader not initialized")
            return

        try:
            while not self._shutdown_event.is_set():
                try:
                    line_bytes = await self._stdin_reader.readline()
                except Exception as e:
                    self.logger.error("Error reading stdin: %s", e)
                    break

                if not line_bytes:
                    self.logger.info("stdin EOF - parent closed connection")
                    break

                line_str = line_bytes.decode('utf-8', errors='ignore').strip()

                if line_str:
                    command_data = CommandMessage.parse(line_str)
                    if command_data:
                        try:
                            await asyncio.wait_for(
                                self._command_queue.put(command_data),
                                timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            self.logger.error("Command queue full, dropping command")
                            StatusMessage.send("error", {"message": "Command queue full"})
                    else:
                        self.logger.warning("Invalid JSON command: %s", line_str[:100])
                        StatusMessage.send("error", {"message": "Invalid JSON command"})

        except Exception as e:
            self.logger.error("stdin reader error: %s", e, exc_info=True)
        finally:
            self._shutdown_event.set()

    async def _command_processor_loop(self, command_handler: BaseCommandHandler) -> None:
        try:
            while not self._shutdown_event.is_set():
                try:
                    command_data = await asyncio.wait_for(
                        self._command_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue  # Check shutdown flag

                try:
                    continue_running = await command_handler.handle_command(command_data)
                    if not continue_running:
                        self.logger.info("Quit command processed, shutting down")
                        self._shutdown_event.set()
                        break
                except Exception as e:
                    self.logger.error("Error processing command: %s", e, exc_info=True)
                    StatusMessage.send("error", {
                        "message": f"Command processing error: {str(e)[:100]}"
                    })

        except Exception as e:
            self.logger.error("Command processor error: %s", e, exc_info=True)
        finally:
            self._shutdown_event.set()

    async def _main_loop(self) -> None:
        await self._shutdown_event.wait()

    async def _on_ready(self) -> None:
        StatusMessage.send("initialized", {
            "module": self.__class__.__name__,
            "ready": True
        })

    async def _on_shutdown(self) -> None:
        pass

    def is_running(self) -> bool:
        return not self._shutdown_event.is_set() and getattr(self.system, 'running', True)
