#!/usr/bin/env python3
"""
Base mode for eye tracker system operations.

Provides shared functionality for all operational modes.
"""

from typing import TYPE_CHECKING
from Modules.base.modes import BaseMode as CoreBaseMode

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem


class BaseMode(CoreBaseMode):
    """Base class for eye tracker system operational modes."""

    def __init__(self, tracker_system: 'TrackerSystem'):
        """
        Initialize base mode.

        Args:
            tracker_system: Reference to TrackerSystem instance
        """
        super().__init__(tracker_system)

    async def start_recording(self) -> None:
        """Start recording."""
        if not self.system.recording:
            if hasattr(self.system, 'recording_manager'):
                await self.system.recording_manager.toggle_recording()
                self.system.recording = True
                self.logger.info("Recording started")

    async def stop_recording(self) -> None:
        """Stop recording."""
        if self.system.recording:
            if hasattr(self.system, 'recording_manager'):
                await self.system.recording_manager.toggle_recording()
                self.system.recording = False
                self.logger.info("Recording stopped")
