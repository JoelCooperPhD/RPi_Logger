#!/usr/bin/env python3
"""
Interactive mode - preview with keyboard controls or headless stdin commands.

Supports two sub-modes:
1. Preview mode: OpenCV windows with keyboard shortcuts
2. Headless interactive: stdin commands without GUI
"""

import datetime
import select
import sys
import threading
import time
from typing import TYPE_CHECKING

import cv2

from .base_mode import BaseMode

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class InteractiveMode(BaseMode):
    """Interactive mode with preview windows or headless stdin control."""

    def __init__(self, camera_system: 'CameraSystem'):
        super().__init__(camera_system)

    def run(self) -> None:
        """Run interactive mode - preview or headless based on show_preview setting."""
        if not self.system.cameras:
            self.logger.error("No cameras available for interactive mode")
            return

        if self.system.show_preview:
            self._run_with_preview()
        else:
            self._run_headless_interactive()

    def _run_headless_interactive(self) -> None:
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

        # Run stdin listener in background thread
        def stdin_listener():
            while self.is_running():
                try:
                    # Check if stdin has data available (non-blocking)
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        line = sys.stdin.readline().strip().lower()
                        if not line:
                            continue

                        cmd = line[0]  # Take first character

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
                            self._take_snapshots(console)
                        else:
                            self.logger.warning("Unknown command: %s (use r/s/q)", cmd)
                            print(f"✗ Unknown command '{cmd}' (use r/s/q)", file=console)
                            console.flush()
                except Exception as e:
                    self.logger.error("Stdin listener error: %s", e)
                    break

        stdin_thread = threading.Thread(target=stdin_listener, daemon=True)
        stdin_thread.start()

        # Just keep cameras active without GUI
        try:
            while self.is_running():
                # Update frame cache to keep pipeline active
                for cam in self.system.cameras:
                    cam.update_preview_cache()
                time.sleep(0.01)  # 100 FPS polling
        except KeyboardInterrupt:
            self.logger.info("Interrupted by user")
            self.system.running = False

        # Wait for stdin thread to finish
        if stdin_thread.is_alive():
            stdin_thread.join(timeout=0.5)

    def _run_with_preview(self) -> None:
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
            for i, frame in enumerate(frames):
                if frame is not None:
                    # Log frame size on first iteration
                    if not logged_frame_sizes:
                        self.logger.info("Camera %d actual frame size: %dx%d",
                                       i, frame.shape[1], frame.shape[0])
                    cv2.imshow(f"Camera {i}", frame)

            if not logged_frame_sizes:
                logged_frame_sizes = True

            # Use waitKey(1) which only waits 1ms - this allows high frame rates
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
                self._take_snapshots(console)

        self.logger.info("All preview windows closed")
        # Gracefully shut down OpenCV Qt event loop
        # Multiple waitKey calls allow Qt to process pending events
        for _ in range(5):
            cv2.waitKey(10)
        cv2.destroyAllWindows()
        # Final event processing to let Qt clean up properly
        for _ in range(5):
            cv2.waitKey(10)
        time.sleep(0.05)  # Give Qt backend time to finish cleanup

    def _take_snapshots(self, console=None) -> None:
        """
        Take snapshots from all cameras.

        Args:
            console: Console output stream (optional)
        """
        if console is None:
            console = self.system.console

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self.system._ensure_session_dir()
        snapshot_count = 0
        for i, cam in enumerate(self.system.cameras):
            frame = cam.update_preview_cache()
            if frame is not None:
                filename = session_dir / f"snapshot_cam{i}_{ts}.jpg"
                cv2.imwrite(str(filename), frame)
                self.logger.info("Saved snapshot %s", filename)
                snapshot_count += 1
        print(f"✓ Saved {snapshot_count} snapshot(s)", file=console)
        console.flush()
