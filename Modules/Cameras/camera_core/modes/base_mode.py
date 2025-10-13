#!/usr/bin/env python3
"""
Base mode for camera system operations.

Provides shared functionality for all operational modes.
"""

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class BaseMode:
    """Base class for camera system operational modes."""

    def __init__(self, camera_system: 'CameraSystem'):
        """
        Initialize base mode.

        Args:
            camera_system: Reference to CameraSystem instance
        """
        self.system = camera_system
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

    def run(self) -> None:
        """
        Run the mode (implement in subclasses).

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement run()")

    def start_recording_all(self) -> None:
        """Start recording on all cameras."""
        if not self.system.recording:
            session_dir = self.system._ensure_session_dir()
            for cam in self.system.cameras:
                cam.start_recording(session_dir)
            self.system.recording = True
            self.logger.info("Recording started")

    def stop_recording_all(self) -> None:
        """Stop recording on all cameras."""
        if self.system.recording:
            for cam in self.system.cameras:
                cam.stop_recording()
            self.system.recording = False
            self.logger.info("Recording stopped")

    def update_preview_frames(self) -> list:
        """
        Update and get preview frames from all cameras.

        Returns:
            List of preview frames (may contain None for unavailable cameras)
        """
        return [cam.update_preview_cache() for cam in self.system.cameras]

    def is_running(self) -> bool:
        """Check if system is still running."""
        return self.system.running and not self.system.shutdown_event.is_set()
