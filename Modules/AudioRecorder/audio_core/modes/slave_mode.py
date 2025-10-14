#!/usr/bin/env python3
"""
Slave mode - JSON command-driven operation.

Listens for commands on stdin and executes them.
Reports status via JSON on stdout.
"""

import asyncio
import sys
from typing import TYPE_CHECKING

from .base_mode import BaseMode
from ..commands import CommandHandler, CommandMessage, StatusMessage

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class SlaveMode(BaseMode):
    """Command-driven slave mode for master-slave architecture."""

    def __init__(self, audio_system: 'AudioSystem'):
        super().__init__(audio_system)
        self.command_handler = CommandHandler(audio_system)

    async def command_listener(self) -> None:
        """
        Listen for commands from stdin in slave mode (async).
        Uses asyncio streams for non-blocking operation.
        """
        loop = asyncio.get_running_loop()

        # Create async stream reader for stdin
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        try:
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        except Exception as e:
            self.logger.error("Failed to setup stdin reader: %s", e)
            return

        while self.is_running():
            try:
                # Read line asynchronously with timeout
                try:
                    line_bytes = await asyncio.wait_for(
                        reader.readline(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    # No data available, continue loop
                    continue

                if not line_bytes:
                    # EOF reached
                    break

                line_str = line_bytes.decode('utf-8').strip()

                if line_str:
                    command_data = CommandMessage.parse(line_str)
                    if command_data:
                        await self.command_handler.handle_command(command_data)
                    else:
                        StatusMessage.send("error", {"message": "Invalid JSON"})

            except Exception as e:
                StatusMessage.send("error", {"message": f"Command error: {e}"})
                self.logger.error("Command listener error: %s", e)
                break

    async def run(self) -> None:
        """Run slave mode - listen for commands."""
        self.system.running = True

        self.logger.info("Slave mode: waiting for commands (JSON protocol)...")

        # Send ready status
        StatusMessage.send("ready", {"message": "Slave mode ready for commands"})

        # Run command listener (uses threading for stdin)
        await self.command_listener()

        self.logger.info("Slave mode ended")
