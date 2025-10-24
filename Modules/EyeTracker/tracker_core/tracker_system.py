
import asyncio
import logging
import sys
from typing import Any

from Modules.base import BaseSystem, ModuleInitializationError, RecordingStateMixin
from .config.tracker_config import TrackerConfig
from .device_manager import DeviceManager
from .stream_handler import StreamHandler
from .frame_processor import FrameProcessor
from .recording import RecordingManager
from .modes import GUIMode, HeadlessMode, SlaveMode

logger = logging.getLogger(__name__)


class TrackerInitializationError(ModuleInitializationError):
    pass


class TrackerSystem(BaseSystem, RecordingStateMixin):

    # Device will connect in background after GUI is created
    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.frame_count = 0
        self.gaze_tracker = None  # Set by GUIMode

        width = getattr(args, 'width', 1280)
        height = getattr(args, 'height', 720)
        self.config = TrackerConfig(
            fps=getattr(args, 'target_fps', 5.0),
            resolution=(width, height),
            output_dir=str(getattr(args, 'session_dir', 'recordings')),
            display_width=getattr(args, 'preview_width', 640)
        )

        self.device_manager = DeviceManager()
        self.stream_handler = StreamHandler()
        self.frame_processor = FrameProcessor(self.config)
        self.recording_manager = RecordingManager(self.config)

    async def _initialize_devices(self) -> None:
        self.logger.info("Initializing tracker system")

        connected = await self.device_manager.connect()
        if not connected:
            raise TrackerInitializationError("Failed to connect to eye tracker device")

        self.initialized = True
        self.logger.info("Tracker system initialized")

        if self.slave_mode or self.enable_gui_commands:
            from logger_core.commands import StatusMessage
            StatusMessage.send("initialized", {"device": "eye_tracker"})

    def _create_mode_instance(self, mode_name: str) -> Any:
        if mode_name in ('tkinter', 'gui', 'interactive'):
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        elif mode_name == 'slave':
            return SlaveMode(self)
        else:  # headless (default fallback)
            return HeadlessMode(self)

    # Phase 1.4: Pause/resume support
    async def pause(self):
        """Pause tracking to save CPU"""
        if self.gaze_tracker is None:
            logger.warning("Cannot pause: tracker not initialized")
            return

        await self.gaze_tracker.pause()
        logger.info("Tracker system paused")

    async def resume(self):
        """Resume tracking"""
        if self.gaze_tracker is None:
            logger.warning("Cannot resume: tracker not initialized")
            return

        await self.gaze_tracker.resume()
        logger.info("Tracker system resumed")

    def is_paused(self) -> bool:
        """Check if paused"""
        if self.gaze_tracker is None:
            return False
        return self.gaze_tracker.is_paused

    async def cleanup(self) -> None:
        self.logger.info("Cleaning up tracker system")
        self.running = False

        await self.stream_handler.stop_streaming()
        await self.recording_manager.cleanup()
        await self.device_manager.cleanup()
        self.frame_processor.destroy_windows()

        self.logger.info("Tracker system cleanup complete")
