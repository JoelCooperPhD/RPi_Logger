#!/usr/bin/env python3
"""
Interactive mode - preview with keyboard controls or headless stdin commands.

Supports two sub-modes:
1. Preview mode: OpenCV windows with keyboard shortcuts
2. Headless interactive: stdin commands without GUI
"""

import asyncio
import datetime
import sys
from typing import TYPE_CHECKING

import cv2

from .base_mode import BaseMode

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class InteractiveMode(BaseMode):
    """Interactive mode with preview windows or headless stdin control."""

    def __init__(self, camera_system: 'CameraSystem'):
        super().__init__(camera_system)

    async def run(self) -> None:
        """Run interactive mode - preview or headless based on show_preview setting."""
        if not self.system.cameras:
            self.logger.error("No cameras available for interactive mode")
            return

        if self.system.show_preview:
            await self._run_with_preview()
        else:
            await self._run_headless_interactive()

    async def _run_headless_interactive(self) -> None:
        """Run in headless interactive mode (stdin commands without GUI)."""
        self.system.running = True

        self.logger.info("Preview disabled - running in headless interactive mode")
        self.logger.info("Commands: 'r' to toggle recording, 's' for snapshot, 'q' to quit")
        self.logger.info("Type command and press Enter")

        # Print control instructions to console (always visible to user)
        console = self.system.console
        print("\n" + "="*60, file=console)
        print("HEADLESS INTERACTIVE MODE", file=console)
        print("="*60, file=console)
        print("Commands:", file=console)
        print("  r + Enter : Toggle recording on/off", file=console)
        print("  s + Enter : Take snapshot from all cameras", file=console)
        print("  q + Enter : Quit application", file=console)
        print("  Ctrl+C    : Also quits gracefully", file=console)
        print("="*60 + "\n", file=console)
        console.flush()

        # Auto-start recording if enabled
        if self.system.auto_start_recording:
            self.start_recording_all()
            print(f"✓ Recording auto-started → {self.system.session_dir.name}", file=console)
            console.flush()

        # Create async stdin reader
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        # Async stdin listener task
        async def stdin_listener():
            while self.is_running():
                try:
                    # Read line with short timeout to allow checking is_running()
                    try:
                        line = await asyncio.wait_for(reader.readline(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue

                    if not line:
                        # EOF reached
                        break

                    cmd = line.decode().strip().lower()
                    if not cmd:
                        continue

                    cmd = cmd[0]  # Take first character

                    if cmd == 'q':
                        self.logger.info("Quit command received")
                        print("✓ Quitting...", file=console)
                        console.flush()
                        self.system.running = False
                        self.system.shutdown_event.set()
                    elif cmd == 'r':
                        if not self.system.recording:
                            self.start_recording_all()
                            print(f"✓ Recording started → {self.system.session_dir.name}", file=console)
                        else:
                            self.stop_recording_all()
                            print("✓ Recording stopped", file=console)
                        console.flush()
                    elif cmd == 's':
                        await self._take_snapshots_async(console)
                    else:
                        self.logger.warning("Unknown command: %s (use r/s/q)", cmd)
                        print(f"✗ Unknown command '{cmd}' (use r/s/q)", file=console)
                        console.flush()
                except Exception as e:
                    self.logger.error("Stdin listener error: %s", e)
                    break

        # Run stdin listener and camera update concurrently
        try:
            await asyncio.gather(
                stdin_listener(),
                self._camera_update_loop(),
                return_exceptions=True
            )
        except KeyboardInterrupt:
            self.logger.info("Interrupted by user")
            self.system.running = False

    async def _camera_update_loop(self):
        """Keep cameras active by updating frame cache."""
        while self.is_running():
            # Update frame cache to keep pipeline active
            for cam in self.system.cameras:
                cam.update_preview_cache()
            await asyncio.sleep(0.01)  # 100 FPS polling

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
            Key code (masked with 0xFF)
        """
        loop = asyncio.get_event_loop()
        key = await loop.run_in_executor(None, cv2.waitKey, delay_ms)
        return key & 0xFF

    async def _run_with_preview(self) -> None:
        """Run with OpenCV preview windows and keyboard controls."""
        self.system.running = True

        # Check if OpenCV window system is available
        try:
            cv2.namedWindow("test_window", cv2.WINDOW_NORMAL)
            cv2.destroyWindow("test_window")
            self.logger.info("OpenCV window system available")
        except Exception as e:
            self.logger.warning("OpenCV window system not available: %s - preview disabled", e)
            self.logger.info("You can still use slave or headless mode for recording without preview")
            return

        # Create windows for available cameras
        self.logger.info("Creating preview windows with size: %dx%d",
                        self.system.args.preview_width, self.system.args.preview_height)
        for i, cam in enumerate(self.system.cameras):
            cv2.namedWindow(f"Camera {i}", cv2.WINDOW_NORMAL)
            cv2.resizeWindow(f"Camera {i}", self.system.args.preview_width, self.system.args.preview_height)
            self.logger.info("Window 'Camera %d' created and resized to %dx%d",
                           i, self.system.args.preview_width, self.system.args.preview_height)

        self.logger.info("Preview mode: 'q' to quit, 's' for snapshot, 'r' to toggle recording")

        # Print control instructions to console (always visible to user)
        console = self.system.console
        print("\n" + "="*60, file=console)
        print("PREVIEW MODE", file=console)
        print("="*60, file=console)
        print("Commands (keyboard shortcuts in preview window):", file=console)
        print("  q : Quit application", file=console)
        print("  r : Toggle recording on/off", file=console)
        print("  s : Take snapshot from all cameras", file=console)
        print("="*60 + "\n", file=console)
        console.flush()

        # Auto-start recording if enabled
        if self.system.auto_start_recording:
            self.start_recording_all()
            print(f"✓ Recording auto-started → {self.system.session_dir.name}", file=console)
            console.flush()

        # Track if we've logged frame sizes
        logged_frame_sizes = False

        while self.is_running():
            frames = self.update_preview_frames()

            # Display frames for available cameras
            # Note: cv2.imshow and cv2.waitKey must run synchronously in main thread for OpenCV to work
            for i, frame in enumerate(frames):
                if frame is not None:
                    # Log frame size on first iteration
                    if not logged_frame_sizes:
                        self.logger.info("Camera %d actual frame size: %dx%d",
                                       i, frame.shape[1], frame.shape[0])
                    cv2.imshow(f"Camera {i}", frame)

            if not logged_frame_sizes:
                logged_frame_sizes = True

            # cv2.waitKey must run synchronously (OpenCV requirement)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                print("✓ Quitting...", file=console)
                console.flush()
                self.system.running = False
            elif key == ord("r"):
                if not self.system.recording:
                    self.start_recording_all()
                    print(f"✓ Recording started → {self.system.session_dir.name}", file=console)
                else:
                    self.stop_recording_all()
                    print("✓ Recording stopped", file=console)
                console.flush()
            elif key == ord("s"):
                await self._take_snapshots_async(console)

            # Small yield to let other tasks run
            await asyncio.sleep(0.001)

        self.logger.info("All preview windows closed")

        # Gracefully shut down OpenCV
        # First allow Qt to process pending events
        for _ in range(3):
            cv2.waitKey(10)

        # Destroy all windows
        cv2.destroyAllWindows()

        # IMPORTANT: Do NOT call waitKey after destroyAllWindows
        # waitKey can leave terminal in weird state
        # Just give Qt a moment to clean up
        await asyncio.sleep(0.1)

        # Force terminal to reset (in case cv2 left it in weird state)
        try:
            import termios
            import sys
            import tty

            # Get current terminal attributes
            fd = sys.stdin.fileno()

            # Flush input buffer
            termios.tcflush(fd, termios.TCIFLUSH)

            # Reset terminal to sane state
            # This ensures terminal is in canonical mode with echo enabled
            attrs = termios.tcgetattr(fd)
            attrs[3] |= termios.ECHO | termios.ICANON  # Enable echo and canonical mode
            termios.tcsetattr(fd, termios.TCSANOW, attrs)

        except Exception as e:
            self.logger.debug("Terminal reset error (non-critical): %s", e)

        self.logger.info("Preview mode cleanup completed")

    async def _take_snapshots_async(self, console=None) -> None:
        """
        Take snapshots from all cameras (async version).

        Args:
            console: Console output stream (optional)
        """
        if console is None:
            console = self.system.console

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self.system._ensure_session_dir()
        snapshot_count = 0

        loop = asyncio.get_event_loop()

        # Gather all frames first (fast)
        frames_to_save = []
        for i, cam in enumerate(self.system.cameras):
            frame = cam.update_preview_cache()
            if frame is not None:
                filename = session_dir / f"snapshot_cam{i}_{ts}.jpg"
                frames_to_save.append((filename, frame, i))

        # Save all frames concurrently using executor (non-blocking)
        async def save_frame(filename, frame, cam_id):
            await loop.run_in_executor(None, cv2.imwrite, str(filename), frame)
            self.logger.info("Saved snapshot %s", filename)

        if frames_to_save:
            await asyncio.gather(*[save_frame(fn, fr, i) for fn, fr, i in frames_to_save])
            snapshot_count = len(frames_to_save)

        print(f"✓ Saved {snapshot_count} snapshot(s)", file=console)
        console.flush()
