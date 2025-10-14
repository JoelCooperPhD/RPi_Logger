#!/usr/bin/env python3
"""
Multi-camera system coordinator.
Manages multiple cameras and delegates to appropriate operational mode.
"""

import asyncio
import datetime
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from picamera2 import Picamera2

from .camera_handler import CameraHandler
from .commands import StatusMessage
from .modes import InteractiveMode, SlaveMode, HeadlessMode
from .constants import THREAD_JOIN_TIMEOUT_SECONDS

logger = logging.getLogger("CameraSystem")


class CameraInitializationError(RuntimeError):
    """Raised when cameras cannot be initialised."""


class CameraSystem:
    """Multi-camera system with interactive, slave, and headless modes."""

    def __init__(self, args):
        self.logger = logging.getLogger("CameraSystem")
        self.cameras = []
        self.running = False
        self.recording = False
        self.args = args
        self.mode = getattr(args, "mode", "interactive")
        self.slave_mode = self.mode == "slave"
        self.headless_mode = self.mode == "headless"
        self.show_preview = getattr(args, "show_preview", True)
        self.auto_start_recording = getattr(args, "auto_start_recording", False)
        self.session_prefix = getattr(args, "session_prefix", "session")
        self.command_thread = None
        self.shutdown_event = asyncio.Event()
        self.device_timeout = getattr(args, "discovery_timeout", 5)
        self.initialized = False

        # Get console stdout for user-facing messages (falls back to sys.stdout if not available)
        self.console = getattr(args, "console_stdout", sys.stdout)

        # Session directory is created in main() and passed via args
        self.session_dir = getattr(args, "session_dir", None)
        if self.session_dir is None:
            # Fallback: create session directory if not provided
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = self.session_prefix.rstrip("_")
            session_name = f"{prefix}_{timestamp}" if prefix else timestamp
            base = Path(self.args.output_dir)
            self.session_dir = base / session_name
            self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_label = self.session_dir.name
        self.logger.info("Session directory: %s", self.session_dir)

        # Frame streaming for UI preview (used by slave mode)
        self.preview_enabled = []  # Will be populated dynamically based on detected cameras

        # Signal handlers are set up in main.py using asyncio signal handlers
        # No need to set them up here

        # Device will be initialized in run() method after signal handlers are ready
        if self.slave_mode:
            StatusMessage.send("initializing", {"device": "cameras"})

    def _ensure_session_dir(self) -> Path:
        """Return the session directory (created at initialization)."""
        return self.session_dir

    async def _initialize_cameras(self):
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
            if self.slave_mode:
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

    # Compatibility methods for mode classes (kept for backward compatibility with StatusMessage)
    def send_status(self, status_type, data=None):
        """Send status message to master (if in slave mode) - delegates to StatusMessage"""
        if self.slave_mode:
            StatusMessage.send(status_type, data)

    async def run(self):
        """Main run method - chooses mode based on configuration and delegates"""
        try:
            # Initialize cameras now that signal handlers are set up
            await self._initialize_cameras()

            # Create and run appropriate mode
            if self.slave_mode:
                mode = SlaveMode(self)
            elif self.headless_mode:
                mode = HeadlessMode(self)
            else:
                mode = InteractiveMode(self)

            await mode.run()

        except KeyboardInterrupt:
            self.logger.info("Camera system cancelled by user")
            if self.slave_mode:
                StatusMessage.send("error", {"message": "Cancelled by user"})
            raise
        except CameraInitializationError:
            raise
        except Exception as e:
            self.logger.error("Unexpected error in run: %s", e)
            if self.slave_mode:
                StatusMessage.send("error", {"message": f"Unexpected error: {e}"})
            raise

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
