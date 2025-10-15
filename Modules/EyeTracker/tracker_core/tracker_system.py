#!/usr/bin/env python3
"""
Eye tracker system orchestrator.

Manages device, streams, and operational modes.
"""

import asyncio
import logging
import sys
from typing import Any

from Modules.base import BaseSystem
from .config.tracker_config import TrackerConfig
from .device_manager import DeviceManager
from .stream_handler import StreamHandler
from .frame_processor import FrameProcessor
from .recording import RecordingManager
from .modes import GUIMode, HeadlessMode, SlaveMode

logger = logging.getLogger(__name__)


class TrackerInitializationError(Exception):
    """Raised when tracker initialization fails."""
    pass


class TrackerSystem(BaseSystem):
    """Main system orchestrator for eye tracking."""

    def __init__(self, args):
        """
        Initialize tracker system.

        Args:
            args: Parsed command line arguments
        """
        # Initialize base system (handles common initialization)
        super().__init__(args)

        # Auto-detect parent communication mode
        # If stdin is not a TTY (i.e., it's a pipe), enable command mode for GUI
        self.enable_gui_commands = getattr(args, "enable_commands", False) or (
            self.gui_mode and not sys.stdin.isatty()
        )

        # Tracker-specific configuration
        self.frame_count = 0
        self.gaze_tracker = None  # Set by GUIMode

        # Create config from args
        width = getattr(args, 'width', 1280)
        height = getattr(args, 'height', 720)
        self.config = TrackerConfig(
            fps=getattr(args, 'target_fps', 5.0),
            resolution=(width, height),
            output_dir=str(getattr(args, 'session_dir', 'recordings')),
            display_width=getattr(args, 'preview_width', 640)
        )

        # Initialize components
        self.device_manager = DeviceManager()
        self.stream_handler = StreamHandler()
        self.frame_processor = FrameProcessor(self.config)
        self.recording_manager = RecordingManager(self.config)

    async def _initialize_devices(self) -> None:
        """Initialize tracker devices - connects to eye tracker."""
        self.logger.info("Initializing tracker system")

        # Connect to device
        connected = await self.device_manager.connect()
        if not connected:
            raise TrackerInitializationError("Failed to connect to eye tracker device")

        self.initialized = True
        self.logger.info("Tracker system initialized")

        # Send initialized status if parent communication is enabled
        if self.slave_mode or self.enable_gui_commands:
            from logger_core.commands import StatusMessage
            StatusMessage.send("initialized", {"device": "eye_tracker"})

    def _create_mode_instance(self, mode_name: str) -> Any:
        """
        Create mode instance based on mode name.

        Args:
            mode_name: Mode name ('gui', 'headless', 'slave', 'tkinter', 'interactive')

        Returns:
            Mode instance (GUIMode, HeadlessMode, or SlaveMode)
        """
        # Normalize mode aliases
        if mode_name in ('tkinter', 'gui', 'interactive'):
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        elif mode_name == 'slave':
            return SlaveMode(self)
        else:  # headless (default fallback)
            return HeadlessMode(self)

    async def cleanup(self) -> None:
        """Clean up all resources."""
        self.logger.info("Cleaning up tracker system")
        self.running = False

        # Clean up components
        await self.stream_handler.stop_streaming()
        await self.recording_manager.cleanup()
        await self.device_manager.cleanup()
        self.frame_processor.destroy_windows()

        self.logger.info("Tracker system cleanup complete")
