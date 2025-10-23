
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

from picamera2 import Picamera2

from Modules.base import BaseSystem, ModuleInitializationError, RecordingStateMixin
from .camera_handler import CameraHandler
from .commands import StatusMessage
from .modes import GUIMode, SlaveMode, HeadlessMode
from .constants import THREAD_JOIN_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class CameraInitializationError(ModuleInitializationError):
    pass


class CameraSystem(BaseSystem, RecordingStateMixin):

    # Cameras will be detected in background after GUI is created
    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.cameras = []
        self.show_preview = getattr(args, "show_preview", True)
        self.auto_start_recording = getattr(args, "auto_start_recording", False)
        self.command_thread = None

        self.preview_enabled = []  # Will be populated dynamically based on detected cameras

    def _ensure_session_dir(self) -> Path:
        return self.session_dir

    async def _initialize_devices(self) -> None:
        self.logger.info("Searching for cameras (timeout: %ds)...", self.device_timeout)

        start_time = time.time()
        cam_infos = []

        self.initialized = False

        loop = asyncio.get_event_loop()

        while time.time() - start_time < self.device_timeout:
            try:
                cam_infos = await loop.run_in_executor(None, Picamera2.global_camera_info)
                if cam_infos:
                    break
            except Exception as e:
                self.logger.debug("Camera detection attempt failed: %s", e)

            if self.shutdown_event.is_set():
                raise KeyboardInterrupt("Device discovery cancelled")

            await asyncio.sleep(0.5)  # Brief pause between attempts

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

        num_cameras = len(cam_infos)
        self.logger.info("Initializing %d camera(s)...", num_cameras)
        try:
            for i in range(num_cameras):
                handler = CameraHandler(cam_infos[i], i, self.args, None)  # Pass None for session_dir
                await handler.start_loops()  # Start async capture/processor loops
                self.cameras.append(handler)
                self.preview_enabled.append(True)  # Enable preview for this camera by default

            self.logger.info("Successfully initialized %d camera(s)", len(self.cameras))

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
        if mode_name == "slave":
            return SlaveMode(self)
        elif mode_name == "headless":
            return HeadlessMode(self)
        else:  # gui or any other mode defaults to GUI
            return GUIMode(self, enable_commands=self.enable_gui_commands)

    async def start_recording(self) -> bool:
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            self.logger.warning("Cannot start recording: %s", error_msg)
            return False

        if not self.cameras:
            self.logger.warning("No cameras available for recording")
            return False

        try:
            for cam in self.cameras:
                cam.start_recording()

            self.recording = True
            self.logger.info("Recording started on %d cameras", len(self.cameras))
            return True

        except Exception as e:
            self.logger.error("Failed to start recording: %s", e)
            self.recording = False
            return False

    async def stop_recording(self) -> bool:
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            self.logger.warning("Cannot stop recording: %s", error_msg)
            return False

        try:
            for cam in self.cameras:
                cam.stop_recording()

            self.recording = False
            self.logger.info("Recording stopped")
            return True

        except Exception as e:
            self.logger.error("Failed to stop recording: %s", e)
            return False

    def send_status(self, status_type, data=None):
        if self.slave_mode:
            StatusMessage.send(status_type, data)

    async def cleanup(self):
        self.running = False
        self.shutdown_event.set()

        if self.recording:
            await self.stop_recording()

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
