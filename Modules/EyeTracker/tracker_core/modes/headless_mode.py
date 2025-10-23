
import asyncio
import logging
from .base_mode import BaseMode

logger = logging.getLogger(__name__)


class HeadlessMode(BaseMode):

    async def run(self) -> None:
        self.logger.info("Running in headless mode")

        from ..gaze_tracker import GazeTracker

        tracker = GazeTracker(
            self.system.config,
            device_manager=self.system.device_manager,
            stream_handler=self.system.stream_handler,
            frame_processor=self.system.frame_processor,
            recording_manager=self.system.recording_manager
        )

        auto_start = getattr(self.system.args, 'auto_start_recording', False)
        if auto_start:
            self.logger.info("Auto-start recording enabled")
            # Start recording after a brief delay to let streams initialize
            asyncio.create_task(self._auto_start_recording(tracker))

        await tracker.run()

    async def _auto_start_recording(self, tracker) -> None:
        await asyncio.sleep(3.0)

        if not tracker.recording_manager.is_recording:
            self.logger.info("Auto-starting recording...")
            await tracker.recording_manager.start_recording()
        else:
            self.logger.info("Recording already started")
