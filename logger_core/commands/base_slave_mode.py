#!/usr/bin/env python3
"""
Base Slave Mode

Abstract base class for module slave modes.
Provides optimized stdin/stdout communication with event-driven asyncio patterns.
"""

import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Optional

from .command_protocol import CommandMessage, StatusMessage
from .base_handler import BaseCommandHandler


class BaseSlaveMode(ABC):
    """
    Abstract base class for module slave modes.

    Provides efficient stdin command listening and stdout status reporting.
    Uses event-driven asyncio without timeout polling for better CPU efficiency.
    """

    def __init__(self, system: Any):
        """
        Initialize slave mode.

        Args:
            system: Reference to module system instance
        """
        self.system = system
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self._stdin_reader: Optional[asyncio.StreamReader] = None
        self._command_queue: asyncio.Queue = asyncio.Queue(maxsize=100)  # Bounded queue
        self._shutdown_event = asyncio.Event()

    @abstractmethod
    def create_command_handler(self) -> BaseCommandHandler:
        """
        Create module-specific command handler.

        Returns:
            Instance of module's CommandHandler (must inherit from BaseCommandHandler)
        """
        pass

    async def run(self) -> None:
        """
        Run slave mode.

        Main entry point for slave mode operation.
        Sets up stdin reader and runs command processing loop.
        """
        self.logger.info("Starting slave mode (optimized asyncio)")

        # Mark system as running
        if hasattr(self.system, 'running'):
            self.system.running = True

        # Create command handler
        command_handler = self.create_command_handler()

        # Setup stdin reader
        try:
            await self._setup_stdin_reader()
        except Exception as e:
            self.logger.error("Failed to setup stdin reader: %s", e)
            StatusMessage.send("error", {"message": f"Failed to setup stdin: {e}"})
            return

        # Send ready status
        await self._on_ready()

        # Run stdin reader and command processor concurrently
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
        """Setup asyncio stream reader for stdin."""
        loop = asyncio.get_running_loop()
        self._stdin_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._stdin_reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        self.logger.debug("stdin reader configured")

    async def _stdin_reader_loop(self) -> None:
        """
        Read commands from stdin and queue them.

        Event-driven - no timeout polling. Blocks efficiently on readline().
        """
        if not self._stdin_reader:
            self.logger.error("stdin reader not initialized")
            return

        try:
            while not self._shutdown_event.is_set():
                # Read line - blocks efficiently without timeout polling
                try:
                    line_bytes = await self._stdin_reader.readline()
                except Exception as e:
                    self.logger.error("Error reading stdin: %s", e)
                    break

                if not line_bytes:
                    # EOF reached - parent closed stdin
                    self.logger.info("stdin EOF - parent closed connection")
                    break

                line_str = line_bytes.decode('utf-8', errors='ignore').strip()

                if line_str:
                    # Parse command
                    command_data = CommandMessage.parse(line_str)
                    if command_data:
                        # Put on queue with timeout to handle full queue
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
            # Signal shutdown
            self._shutdown_event.set()

    async def _command_processor_loop(self, command_handler: BaseCommandHandler) -> None:
        """
        Process commands from queue.

        Event-driven - blocks on queue.get() without timeout polling.

        Args:
            command_handler: Command handler instance
        """
        try:
            while not self._shutdown_event.is_set():
                # Get command from queue with short timeout to check shutdown
                try:
                    command_data = await asyncio.wait_for(
                        self._command_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue  # Check shutdown flag

                # Process command
                try:
                    continue_running = await command_handler.handle_command(command_data)
                    if not continue_running:
                        # Quit command received
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
            # Signal shutdown
            self._shutdown_event.set()

    async def _main_loop(self) -> None:
        """
        Module-specific main loop.

        Override this to implement module-specific operations
        (e.g., frame processing, audio recording, etc.)

        Default implementation just waits for shutdown.
        """
        await self._shutdown_event.wait()

    async def _on_ready(self) -> None:
        """
        Called when slave mode is ready.

        Override to send custom initialization status or perform setup.
        Default sends 'initialized' status.
        """
        StatusMessage.send("initialized", {
            "module": self.__class__.__name__,
            "ready": True
        })

    async def _on_shutdown(self) -> None:
        """
        Called during shutdown.

        Override to perform cleanup operations.
        """
        pass

    def is_running(self) -> bool:
        """
        Check if slave mode is running.

        Returns:
            True if running, False if shutdown
        """
        return not self._shutdown_event.is_set() and getattr(self.system, 'running', True)
