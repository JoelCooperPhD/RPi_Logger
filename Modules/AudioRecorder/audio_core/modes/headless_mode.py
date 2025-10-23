
import asyncio
from typing import TYPE_CHECKING

from .base_mode import BaseMode

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class HeadlessMode(BaseMode):

    def __init__(self, audio_system: 'AudioSystem'):
        super().__init__(audio_system)

    async def run(self) -> None:
        self.system.running = True

        self.logger.info("Headless mode: auto-starting recording...")

        if self.system.auto_start_recording or self.system.selected_devices:
            if self.system.start_recording():
                device_count = len(self.system.active_handlers)
                self.logger.info("Recording started on %d devices", device_count)
            else:
                self.logger.error("Failed to auto-start recording")
        else:
            self.logger.warning("Headless mode with no auto-start and no devices selected")

        while self.is_running():
            await asyncio.sleep(0.1)

        if self.system.recording:
            await self.system.stop_recording()
            self.logger.info("Recording stopped")

        self.logger.info("Headless mode ended")
