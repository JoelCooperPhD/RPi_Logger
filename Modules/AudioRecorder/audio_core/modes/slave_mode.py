#!/usr/bin/env python3
"""
Slave mode - JSON command-driven operation.

Listens for commands on stdin and executes them.
Reports status via JSON on stdout.
"""

from typing import TYPE_CHECKING

from .base_mode import BaseMode
from logger_core.commands import BaseSlaveMode, BaseCommandHandler
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class SlaveMode(BaseSlaveMode, BaseMode):
    """Command-driven slave mode for master-slave architecture."""

    def __init__(self, audio_system: 'AudioSystem'):
        # Initialize both base classes
        BaseSlaveMode.__init__(self, audio_system)
        BaseMode.__init__(self, audio_system)

    def create_command_handler(self) -> BaseCommandHandler:
        """Create audio-specific command handler."""
        return CommandHandler(self.system)

    async def _on_ready(self) -> None:
        """Send ready status when initialized."""
        from logger_core.commands import StatusMessage
        StatusMessage.send("initialized", {"message": "Audio slave mode ready"})
