#!/usr/bin/env python3
"""
Headless mode - continuous recording without UI.

Starts recording immediately and runs until interrupted.
"""

import asyncio
from typing import TYPE_CHECKING

from .base_mode import BaseMode

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class HeadlessMode(BaseMode):
    """Non-interactive mode that records continuously."""

    def __init__(self, camera_system: 'CameraSystem'):
        super().__init__(camera_system)

    async def run(self) -> None:
        """Run headless mode - start recording and maintain until shutdown."""
        self.system.running = True
        self.logger.info("Headless mode: starting continuous recording")

        session_dir = self.system._ensure_session_dir()
        for cam in self.system.cameras:
            cam.start_recording(session_dir)
        self.system.recording = True

        try:
            while self.is_running():
                # Keep cameras active by updating preview cache
                for cam in self.system.cameras:
                    cam.update_preview_cache()
                # Minimal sleep to prevent CPU spinning
                await asyncio.sleep(0.001)
        finally:
            if self.system.recording:
                for cam in self.system.cameras:
                    cam.stop_recording()
                self.system.recording = False
            self.logger.info("Headless mode ended")
