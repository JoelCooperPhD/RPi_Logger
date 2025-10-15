#!/usr/bin/env python3
"""
Multi-camera system coordinator.
Manages multiple cameras and delegates to appropriate operational mode.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

from picamera2 import Picamera2

from Modules.base import BaseSystem
from .camera_handler import CameraHandler
from .commands import StatusMessage
from .modes import GUIMode, SlaveMode, HeadlessMode
from .constants import THREAD_JOIN_TIMEOUT_SECONDS

logger = logging.getLogger("CameraSystem")


class CameraInitializationError(RuntimeError):
    """Raised when cameras cannot be initialised."""


class CameraSystem(BaseSystem):
    """Multi-camera system with GUI and headless modes."""

    def __init__(self, args):
        # Initialize base system (handles common initialization)
        super().__init__(args)

        # Camera-specific configuration
        self.cameras = []
        self.show_preview = getattr(args, "show_preview", True)
        self.auto_start_recording = getattr(args, "auto_start_recording", False)
        self.command_thread = None

        # Auto-detect parent communication mode
        # If stdin is not a TTY (i.e., it's a pipe), enable command mode for GUI
        self.enable_gui_commands = getattr(args, "enable_commands", False) or (
            self.gui_mode and not sys.stdin.isatty()
        )

        # Frame streaming for UI preview (used by slave mode)
        self.preview_enabled = []  # Will be populated dynamically based on detected cameras

    def _ensure_session_dir(self) -> Path:
        """Return the session directory (created at initialization)."""
        return self.session_dir

    async def _initialize_devices(self) -> None:
        """Initialize cameras with timeout and graceful handling"""
        self.logger.info("Searching for cameras (timeout: %ds)...", self.device_timeout)

        start_time = time.time()
        cam_infos = []

        self.initialized = False

        loop = asyncio.get_event_loop()

        # Try to detect cameras with timeout
        while time.time() - start_time < self.device_timeout:
            try:
                # Wrap blocking camera detection in executor
                cam_infos = await loop.run_in_executor(None, Picamera2.global_camera_info)
                if cam_infos:
                    break
            except Exception as e:
                self.logger.debug("Camera detection attempt failed: %s", e)

            # Check if we should abort
            if self.shutdown_event.is_set():
                raise KeyboardInterrupt("Device discovery cancelled")

            await asyncio.sleep(0.5)  # Brief pause between attempts

        # Log found cameras
        for i, info in enumerate(cam_infos):
            self.logger.info("Found camera %d: %s", i, info)

        # Check if we have the required cameras
        if not cam_infos:
            error_msg = f"No cameras found within {self.device_timeout} seconds"
            self.logger.warning(error_msg)
            if self.slave_mode:
                StatusMessage.send("warning", {"message": error_msg})
            raise CameraInitializationError(error_msg)

        min_required = getattr(self.args, "min_cameras", 2)
        if len(cam_infos) < min_required:
            warning_msg = (
                f"Only {len(cam_infos)} camera(s) found, expected at least {min_required}"
            )
            self.logger.warning(warning_msg)
            if not self.args.allow_partial:
                if self.slave_mode:
                    StatusMessage.send("error", {"message": warning_msg})
                raise CameraInitializationError(warning_msg)
            if self.slave_mode:
                StatusMessage.send(
                    "warning",
                    {"message": warning_msg, "cameras": len(cam_infos)},
                )

        # Initialize all detected cameras
        num_cameras = len(cam_infos)
        self.logger.info("Initializing %d camera(s)...", num_cameras)
        try:
            # Don't create session dir yet - wait until first recording/snapshot
            # Just pass output_dir to handlers, they'll use session_dir when recording starts
            for i in range(num_cameras):
                handler = CameraHandler(cam_infos[i], i, self.args, None)  # Pass None for session_dir
                await handler.start_loops()  # Start async capture/processor loops
                self.cameras.append(handler)
                self.preview_enabled.append(True)  # Enable preview for this camera by default

            self.logger.info("Successfully initialized %d camera(s)", len(self.cameras))

            # Send initialized status if parent communication is enabled
            if self.slave_mode or self.enable_gui_commands:
                StatusMessage.send(
                    "initialized",
                    {"cameras": len(self.cameras), "session": self.session_label},
                )
            self.initialized = True

        except Exception as e:
            self.logger.error("Failed to initialize cameras: %s", e)
            if self.slave_mode:
                StatusMessage.send("error", {"message": f"Camera initialization failed: {e}"})
            raise

    def _create_mode_instance(self, mode_name: str) -> Any:
        """
        Create mode instance based on mode name.

        Args:
            mode_name: Mode name ('gui', 'headless', 'slave')

        Returns:
            Mode instance (SlaveMode, HeadlessMode, or GUIMode)
        """
        if mode_name == "slave":
            return SlaveMode(self)
        elif mode_name == "headless":
            return HeadlessMode(self)
        else:  # gui or any other mode defaults to GUI
            return GUIMode(self, enable_commands=self.enable_gui_commands)

    # Compatibility methods for mode classes (kept for backward compatibility with StatusMessage)
    def send_status(self, status_type, data=None):
        """Send status message to master (if in slave mode) - delegates to StatusMessage"""
        if self.slave_mode:
            StatusMessage.send(status_type, data)

    async def cleanup(self):
        """Clean up all camera resources."""
        self.running = False
        self.shutdown_event.set()

        if self.recording:
            for cam in self.cameras:
                try:
                    cam.stop_recording()
                except Exception as e:
                    self.logger.debug("Error stopping recording on camera %d: %s", cam.cam_num, e)
            self.recording = False

        # Clean up all cameras concurrently
        if self.cameras:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*[cam.cleanup() for cam in self.cameras], return_exceptions=True),
                    timeout=THREAD_JOIN_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                self.logger.warning("Camera cleanup did not finish within %d seconds", THREAD_JOIN_TIMEOUT_SECONDS)

        self.cameras.clear()
        self.initialized = False

        self.logger.info("Cleanup completed")
