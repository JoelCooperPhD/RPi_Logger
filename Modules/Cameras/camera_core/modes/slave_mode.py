#!/usr/bin/env python3
"""
Slave mode - JSON command-driven with optional preview.

Listens for commands on stdin and executes them.
Optionally shows preview windows and streams frames via JSON.
"""

import asyncio
import base64
import sys
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

    async def command_listener(self, reader: asyncio.StreamReader) -> None:
        """Listen for commands from stdin in slave mode (async)."""
        while self.is_running():
            try:
                # Read line with timeout to allow checking is_running()
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    # EOF reached
                    break

                line_str = line.decode().strip()
                if line_str:
                    command_data = CommandMessage.parse(line_str)
                    if command_data:
                        await self.command_handler.handle_command(command_data)
                    else:
                        StatusMessage.send("error", {"message": "Invalid JSON"})
            except Exception as e:
                StatusMessage.send("error", {"message": f"Command error: {e}"})
                self.logger.error("Command listener error: %s", e)
                break

    async def _cv2_imshow_async(self, window_name: str, frame) -> None:
        """
        Async wrapper for cv2.imshow to prevent event loop blocking.

        Args:
            window_name: Window name
            frame: Frame to display
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, cv2.imshow, window_name, frame)

    async def _cv2_waitKey_async(self, delay_ms: int = 1) -> int:
        """
        Async wrapper for cv2.waitKey to prevent event loop blocking.

        Args:
            delay_ms: Delay in milliseconds

        Returns:
            Key code
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, cv2.waitKey, delay_ms)

    async def run(self) -> None:
        """Run slave mode - listen for commands and optionally show preview."""
        self.system.running = True

        # Create async stdin reader
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

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

        # Run command listener and frame loop concurrently
        async def frame_loop():
            """Main frame processing and streaming loop."""
            nonlocal last_preview_time
            while self.is_running():
                current_time = time.time()

                # Capture frames from all cameras
                frames = self.update_preview_frames()

                # Display frames if preview is enabled
                # Note: cv2 calls must run synchronously in main thread for OpenCV to work
                if preview_available:
                    for i, frame in enumerate(frames):
                        if frame is not None:
                            cv2.imshow(f"Camera {i}", frame)
                    # Check for window close or key press (1ms wait)
                    cv2.waitKey(1)
                    # Note: In slave mode, we don't act on keypresses (only JSON commands)

                # Send preview frames via JSON if enabled and enough time has passed
                if current_time - last_preview_time >= preview_interval:
                    last_preview_time = current_time

                    for i, frame in enumerate(frames):
                        if (i < len(self.system.preview_enabled) and
                            self.system.preview_enabled[i] and
                            frame is not None):
                            # Encode frame as JPEG (non-blocking via executor)
                            ret, buffer = await loop.run_in_executor(
                                None,
                                cv2.imencode,
                                '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
                            )
                            if ret:
                                # Convert to base64 for JSON transmission
                                frame_b64 = base64.b64encode(buffer).decode('utf-8')
                                StatusMessage.send("preview_frame", {
                                    "camera_id": i,
                                    "frame": frame_b64,
                                    "timestamp": current_time,
                                })

                # Minimal sleep to prevent excessive CPU usage but allow high frame rates
                await asyncio.sleep(0.001)  # 1ms sleep

        # Run both tasks concurrently
        await asyncio.gather(
            self.command_listener(reader),
            frame_loop(),
            return_exceptions=True
        )

        # Clean up OpenCV windows if they were created
        if preview_available:
            cv2.destroyAllWindows()
            for _ in range(5):
                cv2.waitKey(10)

        self.logger.info("Slave mode ended")
