#!/usr/bin/env python3
"""
Slave mode - JSON command-driven headless operation.

Listens for commands on stdin and executes them.
Streams frames via JSON protocol (no local display windows).
Use GUI mode for local display with parent process communication.
"""

import asyncio
import base64
import time
from typing import TYPE_CHECKING

import cv2

from .base_mode import BaseMode
from logger_core.commands import BaseSlaveMode, BaseCommandHandler
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class SlaveMode(BaseSlaveMode, BaseMode):
    """Command-driven slave mode for headless operation (no GUI, no local preview)."""

    def __init__(self, camera_system: 'CameraSystem'):
        # Initialize both base classes
        BaseSlaveMode.__init__(self, camera_system)
        BaseMode.__init__(self, camera_system)

    def create_command_handler(self) -> BaseCommandHandler:
        """Create camera-specific command handler."""
        return CommandHandler(self.system)

    async def _main_loop(self) -> None:
        """
        Main frame processing and streaming loop (no local display).

        Captures frames and optionally sends previews via JSON protocol.
        """
        last_preview_time = 0
        preview_interval = 0.033  # ~30 FPS for preview streaming

        loop = asyncio.get_event_loop()

        while self.is_running():
            current_time = time.time()

            # Capture frames from all cameras (for recording, no local display)
            frames = self.update_preview_frames()

            # Send preview frames via JSON if enabled and enough time has passed
            # This allows remote/parent process to receive frames over JSON protocol
            if current_time - last_preview_time >= preview_interval:
                last_preview_time = current_time

                for i, frame in enumerate(frames):
                    if (i < len(self.system.preview_enabled) and
                        self.system.preview_enabled[i] and
                        frame is not None):
                        # Encode frame as JPEG (non-blocking via executor)
                        try:
                            ret, buffer = await loop.run_in_executor(
                                None,
                                cv2.imencode,
                                '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
                            )
                            if ret:
                                # Convert to base64 for JSON transmission
                                from logger_core.commands import StatusMessage
                                frame_b64 = base64.b64encode(buffer).decode('utf-8')
                                StatusMessage.send("preview_frame", {
                                    "camera_id": i,
                                    "frame": frame_b64,
                                    "timestamp": current_time,
                                })
                        except Exception as e:
                            self.logger.error("Error encoding preview frame: %s", e)

            # Minimal sleep to prevent excessive CPU usage but allow high frame rates
            await asyncio.sleep(0.001)  # 1ms sleep
