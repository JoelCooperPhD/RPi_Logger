#!/usr/bin/env python3
"""
Slave mode - JSON command-driven with optional preview.

Listens for commands on stdin and executes them.
Optionally shows preview windows and streams frames via JSON.
"""

import base64
import select
import sys
import threading
import time
from typing import TYPE_CHECKING

import cv2

from .base_mode import BaseMode
from ..commands import CommandHandler, CommandMessage, StatusMessage

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class SlaveMode(BaseMode):
    """Command-driven slave mode with optional local preview."""

    def __init__(self, camera_system: 'CameraSystem'):
        super().__init__(camera_system)
        self.command_handler = CommandHandler(camera_system)
        self.command_thread = None

    def command_listener(self) -> None:
        """Listen for commands from stdin in slave mode."""
        while self.is_running():
            try:
                # Use select to check if stdin has data available
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    line = sys.stdin.readline().strip()
                    if line:
                        command_data = CommandMessage.parse(line)
                        if command_data:
                            self.command_handler.handle_command(command_data)
                        else:
                            StatusMessage.send("error", {"message": "Invalid JSON"})
            except Exception as e:
                StatusMessage.send("error", {"message": f"Command error: {e}"})
                self.logger.error("Command listener error: %s", e)
                break

    def run(self) -> None:
        """Run slave mode - listen for commands and optionally show preview."""
        self.system.running = True

        # Start command listener thread
        self.command_thread = threading.Thread(target=self.command_listener, daemon=True)
        self.command_thread.start()

        # If preview is enabled, create OpenCV windows for local display
        preview_available = False
        if self.system.show_preview:
            self.logger.info("Slave mode with preview: showing local windows alongside JSON commands")
            try:
                cv2.namedWindow("test_window", cv2.WINDOW_NORMAL)
                cv2.destroyWindow("test_window")
                self.logger.info("OpenCV window system available")

                # Create windows for available cameras
                for i, cam in enumerate(self.system.cameras):
                    cv2.namedWindow(f"Camera {i}", cv2.WINDOW_NORMAL)
                    cv2.resizeWindow(f"Camera {i}", self.system.args.preview_width, self.system.args.preview_height)
                preview_available = True
            except Exception as e:
                self.logger.warning("OpenCV window system not available: %s - disabling preview", e)
                self.system.show_preview = False
        else:
            self.logger.info("Slave mode: waiting for commands (no preview windows)...")

        last_preview_time = 0
        preview_interval = 0.033  # ~30 FPS for preview streaming

        # Keep cameras active
        while self.is_running():
            current_time = time.time()

            # Capture frames from all cameras
            frames = self.update_preview_frames()

            # Display frames if preview is enabled
            if preview_available:
                for i, frame in enumerate(frames):
                    if frame is not None:
                        cv2.imshow(f"Camera {i}", frame)
                # Check for window close or key press (1ms wait to allow high frame rates)
                cv2.waitKey(1)
                # Note: In slave mode, we don't act on keypresses (only JSON commands)

            # Send preview frames via JSON if enabled and enough time has passed
            if current_time - last_preview_time >= preview_interval:
                last_preview_time = current_time

                for i, frame in enumerate(frames):
                    if (i < len(self.system.preview_enabled) and
                        self.system.preview_enabled[i] and
                        frame is not None):
                        # Encode frame as JPEG
                        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                        if ret:
                            # Convert to base64 for JSON transmission
                            frame_b64 = base64.b64encode(buffer).decode('utf-8')
                            StatusMessage.send("preview_frame", {
                                "camera_id": i,
                                "frame": frame_b64,
                                "timestamp": current_time,
                            })

            # Minimal sleep to prevent excessive CPU usage but allow high frame rates
            if not preview_available:
                time.sleep(0.001)  # 1ms sleep - allows up to ~1000 FPS polling

        # Clean up OpenCV windows if they were created
        if preview_available:
            cv2.destroyAllWindows()
            for _ in range(5):
                cv2.waitKey(10)

        self.logger.info("Slave mode ended")
