#!/usr/bin/env python3
"""
Headless mode for eye tracker - delegates to existing GazeTracker.
"""

import asyncio
import logging
from .base_mode import BaseMode

logger = logging.getLogger(__name__)


class HeadlessMode(BaseMode):
    """Headless mode - background operation without display."""

    async def run(self) -> None:
        """Run headless mode - delegates to GazeTracker."""
        self.logger.info("Running in headless mode")

        # Import GazeTracker from the tracker_core
        from ..gaze_tracker import GazeTracker

        # Use existing GazeTracker with system's config
        tracker = GazeTracker(
            self.system.config,
            device_manager=self.system.device_manager,
            stream_handler=self.system.stream_handler,
            frame_processor=self.system.frame_processor,
            recording_manager=self.system.recording_manager
        )

        # Check if auto-start recording is enabled
        auto_start = getattr(self.system.args, 'auto_start_recording', False)
        if auto_start:
            self.logger.info("Auto-start recording enabled")
            # Start recording after a brief delay to let streams initialize
            asyncio.create_task(self._auto_start_recording(tracker))

        # Run the tracker
        await tracker.run()

    async def _auto_start_recording(self, tracker) -> None:
        """Auto-start recording after streams are ready."""
        # Wait for streams to initialize and first frames to arrive
        await asyncio.sleep(3.0)

        if not tracker.recording_manager.is_recording:
            self.logger.info("Auto-starting recording...")
            await tracker.recording_manager.start_recording()
        else:
            self.logger.info("Recording already started")
