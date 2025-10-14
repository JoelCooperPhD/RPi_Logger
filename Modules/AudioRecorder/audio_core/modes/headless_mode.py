#!/usr/bin/env python3
"""
Headless mode - continuous recording without user interaction.

Auto-starts recording and runs until shutdown signal.
"""

import asyncio
from typing import TYPE_CHECKING

from .base_mode import BaseMode

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class HeadlessMode(BaseMode):
    """Headless mode for unattended continuous recording."""

    def __init__(self, audio_system: 'AudioSystem'):
        super().__init__(audio_system)

    async def run(self) -> None:
        """Run headless mode - auto-start recording and wait for shutdown."""
        self.system.running = True

        self.logger.info("Headless mode: auto-starting recording...")

        # Auto-start recording if enabled
        if self.system.auto_start_recording or self.system.selected_devices:
            if self.system.start_recording():
                device_count = len(self.system.active_handlers)
                self.logger.info("Recording started on %d devices", device_count)
            else:
                self.logger.error("Failed to auto-start recording")
        else:
            self.logger.warning("Headless mode with no auto-start and no devices selected")

        # Wait for shutdown signal
        while self.is_running():
            await asyncio.sleep(0.1)

        # Stop recording on shutdown
        if self.system.recording:
            await self.system.stop_recording()
            self.logger.info("Recording stopped")

        self.logger.info("Headless mode ended")
