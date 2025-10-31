
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
            display_width=getattr(args, 'preview_width', 640),
            preview_width=getattr(args, 'preview_width', 640),
            preview_height=getattr(args, 'preview_height', None),
            enable_recording_overlay=getattr(args, 'enable_recording_overlay', True),
            include_gaze_in_recording=getattr(args, 'include_gaze_in_recording', True),
            overlay_font_scale=getattr(args, 'overlay_font_scale', 0.6),
            overlay_thickness=getattr(args, 'overlay_thickness', 1),
            overlay_color_r=getattr(args, 'overlay_color_r', 0),
            overlay_color_g=getattr(args, 'overlay_color_g', 0),
            overlay_color_b=getattr(args, 'overlay_color_b', 0),
            overlay_margin_left=getattr(args, 'overlay_margin_left', 10),
            overlay_line_start_y=getattr(args, 'overlay_line_start_y', 30),
            gaze_circle_radius=getattr(args, 'gaze_circle_radius', 30),
            gaze_circle_thickness=getattr(args, 'gaze_circle_thickness', 3),
            gaze_center_radius=getattr(args, 'gaze_center_radius', 2),
            gaze_shape=getattr(args, 'gaze_shape', 'circle'),
            gaze_color_worn_b=getattr(args, 'gaze_color_worn_b', 255),
            gaze_color_worn_g=getattr(args, 'gaze_color_worn_g', 255),
            gaze_color_worn_r=getattr(args, 'gaze_color_worn_r', 0),
            gaze_color_not_worn_b=getattr(args, 'gaze_color_not_worn_b', 0),
            gaze_color_not_worn_g=getattr(args, 'gaze_color_not_worn_g', 0),
            gaze_color_not_worn_r=getattr(args, 'gaze_color_not_worn_r', 255)
        )

        self.device_manager = DeviceManager()
        self.stream_handler = StreamHandler()
        self.frame_processor = FrameProcessor(self.config)
        self.recording_manager = RecordingManager(self.config)

    async def _initialize_devices(self) -> None:
        self.logger.info("Initializing tracker system")
        self.lifecycle_timer.mark_phase("device_discovery_start")

        if self._should_send_status():
            from logger_core.commands import StatusMessage
            StatusMessage.send("discovering", {"device_type": "eye_tracker", "timeout": self.device_timeout})

        connected = await self.device_manager.connect()
        if not connected:
            raise TrackerInitializationError("Failed to connect to eye tracker device")

        self.initialized = True
        self.lifecycle_timer.mark_phase("device_discovery_complete")
        self.lifecycle_timer.mark_phase("initialized")
        self.logger.info("Tracker system initialized")

        if self._should_send_status():
            from logger_core.commands import StatusMessage
            init_duration = self.lifecycle_timer.get_duration("device_discovery_start", "initialized")
            StatusMessage.send_with_timing("initialized", init_duration, {
                "device_type": "eye_tracker",
                "device_connected": True
            })

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
        self.shutdown_event.set()

        await self.stream_handler.stop_streaming()
        await self.recording_manager.cleanup()
        await self.device_manager.cleanup()
        self.frame_processor.destroy_windows()

        self.initialized = False
        self.logger.info("Tracker system cleanup complete")
