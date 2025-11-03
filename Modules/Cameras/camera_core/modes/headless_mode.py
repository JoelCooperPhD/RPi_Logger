
import asyncio
from typing import TYPE_CHECKING

from .base_mode import BaseMode

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class HeadlessMode(BaseMode):

    def __init__(self, camera_system: 'CameraSystem'):
        super().__init__(camera_system)

    async def run(self) -> None:
        self.system.running = True
        self.logger.info("Headless mode: starting continuous recording")

        started = await self.system.start_recording()
        if not started:
            self.logger.error("Headless mode unable to start recording; shutting down")
            return

        try:
            while self.is_running():
                for cam in self.system.cameras:
                    cam.update_preview_cache()
                # Minimal sleep to prevent CPU spinning
                await asyncio.sleep(0.001)
        finally:
            if self.system.recording:
                await self.system.stop_recording()
            self.logger.info("Headless mode ended")
