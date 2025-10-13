#!/usr/bin/env python3
"""
Multi-camera system coordinator.
Manages multiple cameras, handles master/slave/headless modes, and processes commands.
"""

import base64
import datetime
import json
import logging
import os
import select
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
from picamera2 import Picamera2

from .camera_handler import CameraHandler

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
        self.session_prefix = getattr(args, "session_prefix", "session")
        self.command_thread = None
        self.shutdown_event = threading.Event()
        self.device_timeout = getattr(args, "discovery_timeout", 5)
        self.session_dir: Optional[Path] = None
        self.session_label: Optional[str] = None
        self.initialized = False

        # Frame streaming for UI preview
        self.preview_enabled = [True, True]  # Enable preview by default for up to 2 cameras
        self.last_preview_time = 0
        self.preview_interval = 0.033  # ~30 FPS for preview streaming

        # Setup signal handlers
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)

        # Device will be initialized in run() method after signal handlers are ready
        if self.slave_mode:
            self.send_status("initializing", {"device": "cameras"})

    def _ensure_session_dir(self) -> Path:
        if self.session_dir is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = self.session_prefix.rstrip("_")
            session_name = f"{prefix}_{timestamp}" if prefix else timestamp
            base = Path(self.args.output_dir)
            self.session_dir = base / session_name
            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.session_label = self.session_dir.name
            self.logger.info("New recording session directory: %s", self.session_dir)
        return self.session_dir

    def _initialize_cameras(self):
        """Initialize cameras with timeout and graceful handling"""
        self.logger.info("Searching for cameras (timeout: %ds)...", self.device_timeout)

        start_time = time.time()
        cam_infos = []

        self.initialized = False

        # Try to detect cameras with timeout
        while time.time() - start_time < self.device_timeout:
            try:
                cam_infos = Picamera2.global_camera_info()
                if cam_infos:
                    break
            except Exception as e:
                self.logger.debug("Camera detection attempt failed: %s", e)

            # Check if we should abort
            if self.shutdown_event.is_set():
                raise KeyboardInterrupt("Device discovery cancelled")

            time.sleep(0.5)  # Brief pause between attempts

        # Log found cameras
        for i, info in enumerate(cam_infos):
            self.logger.info("Found camera %d: %s", i, info)

        # Check if we have the required cameras
        if not cam_infos:
            error_msg = f"No cameras found within {self.device_timeout} seconds"
            self.logger.warning(error_msg)
            if self.slave_mode:
                self.send_status("warning", {"message": error_msg})
            raise CameraInitializationError(error_msg)

        min_required = getattr(self.args, "min_cameras", 2)
        if len(cam_infos) < min_required:
            warning_msg = (
                f"Only {len(cam_infos)} camera(s) found, expected at least {min_required}"
            )
            self.logger.warning(warning_msg)
            if not self.args.allow_partial:
                if self.slave_mode:
                    self.send_status("error", {"message": warning_msg})
                raise CameraInitializationError(warning_msg)
            if self.slave_mode:
                self.send_status(
                    "warning",
                    {"message": warning_msg, "cameras": len(cam_infos)},
                )

        # Initialize available cameras
        self.logger.info("Initializing %d camera(s)...", min(len(cam_infos), 2))
        try:
            # Don't create session dir yet - wait until first recording/snapshot
            # Just pass output_dir to handlers, they'll use session_dir when recording starts
            for i in range(min(len(cam_infos), 2)):
                handler = CameraHandler(cam_infos[i], i, self.args, None)  # Pass None for session_dir
                handler.start_loops()  # Start async capture/collator/processor loops
                self.cameras.append(handler)

            self.logger.info("Successfully initialized %d camera(s)", len(self.cameras))
            if self.slave_mode:
                self.send_status(
                    "initialized",
                    {"cameras": len(self.cameras), "session": self.session_label},
                )
            self.initialized = True

        except Exception as e:
            self.logger.error("Failed to initialize cameras: %s", e)
            if self.slave_mode:
                self.send_status("error", {"message": f"Camera initialization failed: {e}"})
            raise

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info("Received signal %d, shutting down...", signum)
        self.running = False
        self.shutdown_event.set()
        if self.slave_mode:
            self.send_status("shutdown", {"signal": signum})

    def send_status(self, status_type, data=None):
        """Send status message to master (if in slave mode)"""
        if not self.slave_mode:
            return

        message = {
            "type": "status",
            "status": status_type,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data or {}
        }
        # Force to stdout for master communication
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    def handle_command(self, command_data):
        """Handle command from master"""
        try:
            cmd = command_data.get("command")

            if cmd == "start_recording":
                if not self.recording:
                    session_dir = self._ensure_session_dir()
                    for cam in self.cameras:
                        cam.start_recording(session_dir)
                    self.recording = True
                    self.send_status(
                        "recording_started",
                        {
                            "session": self.session_label,
                            "files": [str(cam.recorder) for cam in self.cameras if cam.recorder],
                        },
                    )
                else:
                    self.send_status("error", {"message": "Already recording"})

            elif cmd == "stop_recording":
                if self.recording:
                    for cam in self.cameras:
                        cam.stop_recording()
                    self.recording = False
                    self.send_status(
                        "recording_stopped",
                        {
                            "session": self.session_label,
                            "files": [
                                str(cam.last_recording)
                                for cam in self.cameras
                                if cam.last_recording is not None
                            ],
                        },
                    )
                else:
                    self.send_status("error", {"message": "Not recording"})

            elif cmd == "take_snapshot":
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filenames = []
                session_dir = self._ensure_session_dir()
                for i, cam in enumerate(self.cameras):
                    frame = cam.update_preview_cache()
                    if frame is not None:
                        filename = session_dir / f"snapshot_cam{i}_{ts}.jpg"
                        cv2.imwrite(str(filename), frame)
                        filenames.append(str(filename))
                self.send_status("snapshot_taken", {"files": filenames})

            elif cmd == "get_status":
                status_data = {
                    "recording": self.recording,
                    "session": self.session_label,
                    "cameras": [
                        {
                            "cam_num": cam.cam_num,
                            "recording": cam.recording,
                            "capture_fps": round(cam.capture_loop.get_fps(), 2),
                            "collation_fps": round(cam.collator_loop.get_fps(), 2),
                            "captured_frames": cam.capture_loop.get_frame_count(),
                            "collated_frames": cam.collator_loop.get_frame_count(),
                            "duplicated_frames": cam.recording_manager.duplicated_frames,
                            "recorded_frames": cam.recording_manager.written_frames,
                            "output": str(cam.recording_manager.video_path) if cam.recording_manager.video_path else None,
                        } for cam in self.cameras
                    ]
                }
                self.send_status("status_report", status_data)

            elif cmd == "toggle_preview":
                cam_num = command_data.get("camera_id", 0)
                enabled = command_data.get("enabled", True)

                if 0 <= cam_num < len(self.preview_enabled):
                    self.preview_enabled[cam_num] = enabled
                    self.send_status(
                        "preview_toggled",
                        {"camera_id": cam_num, "enabled": enabled},
                    )
                else:
                    self.send_status("error", {"message": f"Invalid camera_id: {cam_num}"})

            elif cmd == "quit":
                self.running = False
                self.shutdown_event.set()
                self.send_status("quitting")

            else:
                self.send_status("error", {"message": f"Unknown command: {cmd}"})

        except Exception as e:
            self.send_status("error", {"message": str(e)})

    def command_listener(self):
        """Listen for commands from stdin in slave mode"""
        while self.running and not self.shutdown_event.is_set():
            try:
                # Use select to check if stdin has data available
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    line = sys.stdin.readline().strip()
                    if line:
                        command_data = json.loads(line)
                        self.handle_command(command_data)
            except json.JSONDecodeError as e:
                self.send_status("error", {"message": f"Invalid JSON: {e}"})
            except Exception as e:
                self.send_status("error", {"message": f"Command error: {e}"})
                break

    def preview_loop(self):
        """Interactive preview mode (standalone only)"""
        if not self.cameras:
            self.logger.error("No cameras available for preview")
            return

        self.running = True

        # Set OpenCV to use GTK backend if available (more stable than Qt)
        try:
            cv2.namedWindow("test_window", cv2.WINDOW_NORMAL)
            cv2.destroyWindow("test_window")
            self.logger.info("OpenCV window system available")
        except Exception as e:
            self.logger.warning("OpenCV window system not available: %s - preview disabled", e)
            self.logger.info("You can still use slave or headless mode for recording without preview")
            return

        # Create windows for available cameras
        for i, cam in enumerate(self.cameras):
            cv2.namedWindow(f"Camera {i}", cv2.WINDOW_NORMAL)
            cv2.resizeWindow(f"Camera {i}", self.args.preview_width, self.args.preview_height)

        self.logger.info("Preview mode: 'q' to quit, 's' for snapshot, 'r' to toggle recording")

        while self.running and not self.shutdown_event.is_set():
            frames = [cam.update_preview_cache() for cam in self.cameras]

            # Display frames for available cameras
            for i, frame in enumerate(frames):
                if frame is not None:
                    cv2.imshow(f"Camera {i}", frame)

            # Use waitKey(1) which only waits 1ms - this allows high frame rates
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                self.running = False
            elif key == ord("r"):
                if not self.recording:
                    session_dir = self._ensure_session_dir()
                    for cam in self.cameras:
                        cam.start_recording(session_dir)
                    self.recording = True
                else:
                    for cam in self.cameras:
                        cam.stop_recording()
                    self.recording = False
            elif key == ord("s"):
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                session_dir = self._ensure_session_dir()
                for i, frame in enumerate(frames):
                    if frame is not None:
                        filename = session_dir / f"snapshot_cam{i}_{ts}.jpg"
                        cv2.imwrite(str(filename), frame)
                        self.logger.info("Saved snapshot %s", filename)

        self.logger.info("All preview windows closed")
        cv2.destroyAllWindows()

    def slave_loop(self):
        """Command-driven slave mode (no GUI)"""
        self.running = True

        # Start command listener thread
        self.command_thread = threading.Thread(target=self.command_listener, daemon=True)
        self.command_thread.start()

        self.logger.info("Slave mode: waiting for commands...")

        # Keep cameras active but don't display
        while self.running and not self.shutdown_event.is_set():
            current_time = time.time()

            # Capture frames from all cameras
            frames = [cam.update_preview_cache() for cam in self.cameras]

            # Send preview frames if enabled and enough time has passed
            if current_time - self.last_preview_time >= self.preview_interval:
                self.last_preview_time = current_time

                for i, frame in enumerate(frames):
                    if i < len(self.preview_enabled) and self.preview_enabled[i] and frame is not None:
                        # Encode frame as JPEG
                        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                        if ret:
                            # Convert to base64 for JSON transmission
                            frame_b64 = base64.b64encode(buffer).decode('utf-8')
                            logger.info(f"Sending preview frame for camera {i}, base64 length: {len(frame_b64)}")
                            self.send_status("preview_frame", {
                                "camera_id": i,
                                "frame": frame_b64,
                                "timestamp": current_time,
                            })

            # Minimal sleep to prevent excessive CPU usage but allow high frame rates
            time.sleep(0.001)  # 1ms sleep - allows up to ~1000 FPS polling

        self.logger.info("Slave mode ended")

    def headless_loop(self):
        """Non-interactive mode that records immediately."""
        self.running = True
        self.logger.info("Headless mode: starting continuous recording")
        session_dir = self._ensure_session_dir()
        for cam in self.cameras:
            cam.start_recording(session_dir)
        self.recording = True

        try:
            while self.running and not self.shutdown_event.is_set():
                for cam in self.cameras:
                    cam.update_preview_cache()
                # Minimal sleep to prevent CPU spinning
                time.sleep(0.001)
        finally:
            if self.recording:
                for cam in self.cameras:
                    cam.stop_recording()
                self.recording = False
            self.logger.info("Headless mode ended")

    def run(self):
        """Main run method - chooses mode based on configuration"""
        try:
            # Initialize cameras now that signal handlers are set up
            self._initialize_cameras()

            if self.slave_mode:
                self.slave_loop()
            elif self.headless_mode:
                self.headless_loop()
            else:
                self.preview_loop()

        except KeyboardInterrupt:
            self.logger.info("Camera system cancelled by user")
            if self.slave_mode:
                self.send_status("error", {"message": "Cancelled by user"})
            raise
        except CameraInitializationError:
            raise
        except Exception as e:
            self.logger.error("Unexpected error in run: %s", e)
            if self.slave_mode:
                self.send_status("error", {"message": f"Unexpected error: {e}"})
            raise

    def cleanup(self):
        self.logger.info("Cleaning up cameras...")
        self.running = False
        for cam in self.cameras:
            cam.cleanup()
        self.cameras.clear()
        self.initialized = False
        if self.command_thread and self.command_thread.is_alive():
            self.shutdown_event.set()
            self.command_thread.join(timeout=1.0)
        self.logger.info("Cleanup completed")
