#!/usr/bin/env python3
"""
GUI mode - interactive graphical interface with async integration.

Provides a comprehensive tkinter GUI for eye tracker control while running
tracking in async background tasks.
"""

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from .base_mode import BaseMode
from ..interfaces.gui import TkinterGUI
from ..commands import CommandHandler, CommandMessage, StatusMessage

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem


logger = logging.getLogger("GUIMode")


class GUIMode(BaseMode):
    """Tkinter GUI mode with async tracker integration."""

    def __init__(self, tracker_system: 'TrackerSystem', enable_commands: bool = False):
        super().__init__(tracker_system)
        self.gui: TkinterGUI = None
        self.preview_task = None
        self.gaze_tracker = None
        self.enable_commands = enable_commands
        self.command_handler = None  # Will be initialized after GUI is created
        self.command_task = None

    async def run(self) -> None:
        """Run GUI mode with async tracker system."""
        self.system.running = True

        # Create GUI
        self.gui = TkinterGUI(self.system, self.system.args)

        # Initialize command handler with GUI reference (needed for get_geometry)
        if self.enable_commands:
            self.command_handler = CommandHandler(self.system, gui=self.gui)
            self.logger.info("Starting GUI mode with parent command support")
        else:
            self.logger.info("Starting GUI mode")

        # Import GazeTracker
        from ..gaze_tracker import GazeTracker

        # Create GazeTracker instance with display disabled (GUI will handle display)
        self.gaze_tracker = GazeTracker(
            self.system.config,
            device_manager=self.system.device_manager,
            stream_handler=self.system.stream_handler,
            frame_processor=self.system.frame_processor,
            recording_manager=self.system.recording_manager,
            display_enabled=False  # GUI displays frames, not OpenCV window
        )

        # Store reference in system for GUI access
        self.system.gaze_tracker = self.gaze_tracker

        # Auto-start recording if enabled
        if getattr(self.system.args, 'auto_start_recording', False):
            asyncio.create_task(self._auto_start_recording())

        # Start preview update task
        self.preview_task = asyncio.create_task(self._preview_update_loop())

        # Start gaze tracker task
        tracker_task = asyncio.create_task(self.gaze_tracker.run())

        # Start command listener if parent communication enabled
        if self.enable_commands:
            reader = await self._setup_stdin_reader()
            self.command_task = asyncio.create_task(self._command_listener(reader))

        # Run GUI in async context
        try:
            await self._run_gui_async()
        finally:
            # Cancel tasks
            if self.preview_task and not self.preview_task.done():
                self.preview_task.cancel()
            if tracker_task and not tracker_task.done():
                tracker_task.cancel()

            # Cancel command task
            if self.command_task and not self.command_task.done():
                self.command_task.cancel()

            # Wait for tasks to complete
            tasks_to_wait = []
            if self.preview_task:
                tasks_to_wait.append(self.preview_task)
            if tracker_task:
                tasks_to_wait.append(tracker_task)
            if self.command_task:
                tasks_to_wait.append(self.command_task)

            if tasks_to_wait:
                await asyncio.gather(*tasks_to_wait, return_exceptions=True)

    async def _auto_start_recording(self):
        """Auto-start recording after streams are ready."""
        # Wait for streams to initialize
        await asyncio.sleep(3.0)

        if not self.system.recording_manager.is_recording:
            self.logger.info("Auto-starting recording...")
            await self.system.recording_manager.start_recording()
        else:
            self.logger.info("Recording already started")

    async def _run_gui_async(self):
        """
        Run tkinter GUI in async context.

        Uses asyncio-friendly approach to run tkinter mainloop.
        """
        loop = asyncio.get_event_loop()

        # Run tkinter updates in small chunks to allow async operations
        def update_gui():
            """Update GUI and schedule next update."""
            try:
                if self.gui.root.winfo_exists():
                    self.gui.root.update()
                    # Schedule next update
                    if self.system.running:
                        loop.call_later(0.01, update_gui)  # 100 Hz GUI updates
                else:
                    # Window was closed
                    self.system.running = False
            except tk.TclError:
                # Window destroyed
                self.system.running = False
            except Exception as e:
                self.logger.error("GUI update error: %s", e)
                self.system.running = False

        # Start GUI update loop
        import tkinter as tk
        try:
            loop.call_soon(update_gui)

            # Wait for shutdown
            await self.system.shutdown_event.wait()

        finally:
            # Destroy GUI
            if self.gui:
                try:
                    self.gui.destroy()
                except Exception as e:
                    self.logger.debug("Error destroying GUI: %s", e)

    async def _preview_update_loop(self):
        """
        Async loop to update eye tracker preview display.

        Updates at ~10 FPS to reduce GUI overhead.
        """
        update_interval = 1.0 / getattr(self.system.args, 'gui_preview_update_hz', 10)

        while self.is_running():
            try:
                # Store latest display frame for GUI access
                if self.gaze_tracker and hasattr(self.gaze_tracker, '_latest_display_frame'):
                    # Frame is already stored by gaze_tracker
                    pass

                # Update preview in GUI (thread-safe via tkinter after())
                if self.gui and self.gui.root.winfo_exists():
                    self.gui.root.after(0, self.gui.update_preview_frame)

                await asyncio.sleep(update_interval)
            except Exception as e:
                self.logger.debug("Preview update error: %s", e)
                break

    async def _setup_stdin_reader(self) -> asyncio.StreamReader:
        """
        Set up async stdin reader for parent communication.

        Returns:
            AsyncIO StreamReader connected to stdin
        """
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        return reader

    async def _command_listener(self, reader: asyncio.StreamReader) -> None:
        """
        Listen for commands from parent process via stdin.

        Commands are JSON-formatted, one per line.
        Status updates are sent to stdout as JSON.

        Args:
            reader: AsyncIO StreamReader for stdin
        """
        self.logger.info("Command listener started (parent communication enabled)")

        while self.is_running():
            try:
                # Read line with timeout to allow checking is_running()
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    # EOF reached - parent closed stdin
                    self.logger.info("Parent closed stdin, initiating shutdown")
                    self.system.running = False
                    self.system.shutdown_event.set()
                    break

                line_str = line.decode().strip()
                if line_str:
                    command_data = CommandMessage.parse(line_str)
                    if command_data:
                        # Handle command and check for quit
                        continue_running = await self._handle_command_with_gui_sync(command_data)
                        if not continue_running:
                            # Quit command received - exit listener
                            self.logger.info("Quit command received, exiting command listener")
                            break
                    else:
                        StatusMessage.send("error", {"message": "Invalid JSON"})

            except Exception as e:
                StatusMessage.send("error", {"message": f"Command error: {e}"})
                self.logger.error("Command listener error: %s", e)
                break

        self.logger.info("Command listener stopped")

    async def _handle_command_with_gui_sync(self, command_data: dict) -> bool:
        """
        Handle command and sync GUI state.

        This wraps the standard command handler and ensures the GUI
        reflects changes made by commands from parent process.

        Args:
            command_data: Parsed command dict from JSON

        Returns:
            True to continue, False to shutdown (quit command received)
        """
        cmd = command_data.get("command")

        # Execute command via standard handler (returns False for quit command)
        continue_running = await self.command_handler.handle_command(command_data)

        if not continue_running:
            # Quit command received - trigger shutdown
            return False

        # Sync GUI state after command execution (thread-safe via root.after)
        if self.gui and self.gui.root.winfo_exists():
            if cmd == "start_recording":
                # Ensure GUI reflects recording state
                self.gui.root.after(0, self._sync_gui_recording_state)
            elif cmd == "stop_recording":
                # Ensure GUI reflects stopped state
                self.gui.root.after(0, self._sync_gui_recording_state)

        return True

    def _sync_gui_recording_state(self):
        """
        Sync GUI to reflect current recording state.

        Called from command handler to update GUI when parent
        sends start/stop commands.
        """
        if not self.gui:
            return

        if self.system.recording_manager.is_recording:
            # Update window title to show recording
            self.gui.root.title("Eye Tracker - ⬤ RECORDING")
        else:
            # Update window title to default
            self.gui.root.title("Eye Tracker")
