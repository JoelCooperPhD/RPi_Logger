#!/usr/bin/env python3
"""
Slave mode for eye tracker - JSON command-driven operation.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from .base_mode import BaseMode
from logger_core.commands import BaseSlaveMode, BaseCommandHandler, StatusMessage
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem

logger = logging.getLogger(__name__)


class SlaveMode(BaseSlaveMode, BaseMode):
    """Slave mode - JSON command protocol via stdin/stdout."""

    def __init__(self, tracker_system: 'TrackerSystem'):
        """Initialize slave mode."""
        # Initialize both base classes
        BaseSlaveMode.__init__(self, tracker_system)
        BaseMode.__init__(self, tracker_system)

    def create_command_handler(self) -> BaseCommandHandler:
        """Create tracker-specific command handler."""
        return CommandHandler(self.system)

    async def _main_loop(self) -> None:
        """
        Main tracker loop.

        Runs the gaze tracker in parallel with command processing.
        """
        from ..gaze_tracker import GazeTracker

        # Use existing GazeTracker with system's config
        tracker = GazeTracker(
            self.system.config,
            device_manager=self.system.device_manager,
            stream_handler=self.system.stream_handler,
            frame_processor=self.system.frame_processor,
            recording_manager=self.system.recording_manager
        )

        # Run tracker until shutdown
        try:
            await tracker.run()
        except Exception as e:
            self.logger.error("Tracker error: %s", e, exc_info=True)
            StatusMessage.send("error", {"message": f"Tracker error: {str(e)[:100]}"})

    async def _on_ready(self) -> None:
        """Send ready status when initialized."""
        StatusMessage.send("initialized", {"message": "Eye tracker slave mode ready"})
