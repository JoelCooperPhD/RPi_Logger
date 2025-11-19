
import asyncio
import logging
from .base_mode import BaseMode

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


class HeadlessMode(BaseMode):

    async def run(self) -> None:
        self.logger.info("Running in headless mode")

        tracker = self.system.tracker_handler.ensure_tracker(display_enabled=True)

        auto_start = getattr(self.system.args, 'auto_start_recording', False)
        if auto_start:
            self.logger.info("Auto-start recording enabled")
            # Start recording after a brief delay to let streams initialize
            asyncio.create_task(self._auto_start_recording())

        await self.system.tracker_handler.run_foreground(display_enabled=True)

    async def _auto_start_recording(self) -> None:
        await asyncio.sleep(3.0)

        if not self.system.recording_manager.is_recording:
            self.logger.info("Auto-starting recording...")
            await self.system.start_recording()
        else:
            self.logger.info("Recording already started")
