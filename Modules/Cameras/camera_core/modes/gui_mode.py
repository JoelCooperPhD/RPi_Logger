#!/usr/bin/env python3
"""
GUI mode - interactive graphical interface with async integration.

Provides a comprehensive tkinter GUI for camera control while running
cameras in async background tasks.

Supports two operation modes:
1. Standalone: User interacts directly with GUI
2. Parent-controlled: Parent process sends commands via stdin/stdout
"""

import asyncio
import logging
import sys
from typing import TYPE_CHECKING, Optional

from .base_mode import BaseMode
from ..interfaces.gui import TkinterGUI
from ..commands import CommandHandler, CommandMessage, StatusMessage

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


logger = logging.getLogger("GUIMode")


class GUIMode(BaseMode):
    """
    Tkinter GUI mode with async camera integration.

    Can run standalone or with parent process communication via stdin/stdout.
    """

    def __init__(self, camera_system: 'CameraSystem', enable_commands: bool = False):
        super().__init__(camera_system)
        self.gui: TkinterGUI = None
        self.preview_task = None
        self.enable_commands = enable_commands
        self.command_handler = None  # Will be initialized after GUI is created
        self.command_task = None

    async def run(self) -> None:
        """Run GUI mode with async camera system."""
        if not self.system.cameras:
            self.logger.error("No cameras available for GUI mode")
            return

        self.system.running = True

        # Create GUI
        self.gui = TkinterGUI(self.system, self.system.args)

        # Create preview canvases after cameras are initialized
        self.gui.create_preview_canvases()

        # Initialize command handler with GUI reference (needed for get_geometry)
        if self.enable_commands:
            self.command_handler = CommandHandler(self.system, gui=self.gui)
            self.logger.info("Starting GUI mode with parent command support")
        else:
            self.logger.info("Starting GUI mode (standalone)")

        # Auto-start recording if enabled
        if self.system.auto_start_recording:
            self.gui._start_recording()

        # Start preview update task
        self.preview_task = asyncio.create_task(self._preview_update_loop())

        # Start command listener if parent communication enabled
        if self.enable_commands:
            reader = await self._setup_stdin_reader()
            self.command_task = asyncio.create_task(self._command_listener(reader))

        # Run all tasks concurrently
        try:
            tasks = [
                self._run_gui_async(),
                self.preview_task,
            ]

            if self.command_task:
                tasks.append(self.command_task)

            await asyncio.gather(*tasks, return_exceptions=True)

        finally:
            # Cancel preview task
            if self.preview_task and not self.preview_task.done():
                self.preview_task.cancel()

            # Cancel command task
            if self.command_task and not self.command_task.done():
                self.command_task.cancel()

            # Wait for tasks to complete
            pending = []
            if self.preview_task:
                pending.append(self.preview_task)
            if self.command_task:
                pending.append(self.command_task)

            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

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
        Async loop to update camera preview displays.

        Updates at ~10 FPS to reduce GUI overhead.
        """
        while self.is_running():
            try:
                # Update previews in GUI (thread-safe via tkinter after())
                if self.gui and self.gui.root.winfo_exists():
                    self.gui.root.after(0, self.gui.update_preview_frames)

                await asyncio.sleep(0.1)  # 10 Hz preview rate
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

        if self.system.recording:
            # Update window title to show recording
            self.gui.root.title(f"Camera System - ⬤ RECORDING - Session: {self.system.session_label}")

            # Disable camera toggles during recording (safety)
            for i in range(len(self.system.cameras)):
                try:
                    self.gui.view_menu.entryconfig(f"Camera {i}", state='disabled')
                except Exception:
                    pass
        else:
            # Update window title to default
            self.gui.root.title("Camera System")

            # Re-enable camera toggles after recording
            for i in range(len(self.system.cameras)):
                try:
                    self.gui.view_menu.entryconfig(f"Camera {i}", state='normal')
                except Exception:
                    pass
