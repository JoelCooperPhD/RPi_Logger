#!/usr/bin/env python3
"""
Base GUI Mode - Abstract base class for GUI modes with async integration.

Provides common functionality for:
- Async tkinter event loop integration
- Parent process command communication (stdin/stdout)
- Preview update loops
- GUI state synchronization
"""

import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk

from .base_mode import BaseMode
from logger_core.commands import BaseCommandHandler, CommandMessage, StatusMessage


class BaseGUIMode(BaseMode, ABC):
    """
    Abstract base class for GUI modes with async tkinter integration.

    Provides common async patterns for:
    - Running tkinter GUI in async context
    - Listening for commands from parent process
    - Updating preview displays
    - Synchronizing GUI state with command execution

    Subclasses must implement:
    - create_gui() - Create and configure GUI window
    - create_command_handler() - Create command handler instance
    - Additional hooks for module-specific behavior
    """

    def __init__(self, system: Any, enable_commands: bool = False):
        """
        Initialize base GUI mode.

        Args:
            system: Reference to module system instance
            enable_commands: Enable parent command communication via stdin/stdout
        """
        super().__init__(system)
        self.enable_commands = enable_commands
        self.gui: Optional[Any] = None
        self.command_handler: Optional[BaseCommandHandler] = None
        self.command_task: Optional[asyncio.Task] = None
        self.preview_task: Optional[asyncio.Task] = None

    @abstractmethod
    def create_gui(self) -> Any:
        """
        Create and configure GUI window.

        Subclasses must implement this to create their specific GUI.

        Returns:
            GUI instance (typically with 'root' or 'window' attribute)
        """
        pass

    @abstractmethod
    def create_command_handler(self, gui: Any) -> BaseCommandHandler:
        """
        Create command handler instance for this module.

        Args:
            gui: GUI instance (for get_geometry support)

        Returns:
            Module-specific command handler
        """
        pass

    def get_preview_update_interval(self) -> float:
        """
        Get preview update interval in seconds.

        Override to customize preview update frequency.
        Default: 0.1 seconds (10 Hz)

        Returns:
            Update interval in seconds
        """
        return 0.1

    async def update_preview(self) -> None:
        """
        Update preview display(s).

        Override this to implement module-specific preview updates.
        Called periodically by preview update loop.

        Default implementation does nothing.
        """
        pass

    def sync_recording_state(self) -> None:
        """
        Synchronize GUI to reflect current recording state.

        Override this to update GUI elements when recording state changes.
        Called after start_recording and stop_recording commands.

        Default implementation does nothing.
        """
        pass

    def get_gui_window(self) -> Optional[Any]:
        """
        Get the main tkinter window object.

        Tries to find window via common attribute names (root, window).
        Override if your GUI uses a different attribute name.

        Returns:
            Tkinter window object, or None if not found
        """
        if self.gui:
            if hasattr(self.gui, 'root'):
                return self.gui.root
            elif hasattr(self.gui, 'window'):
                return self.gui.window
        return None

    async def run(self) -> None:
        """
        Run GUI mode with async system.

        Main entry point for GUI mode operation.
        Orchestrates GUI creation, command listening, and preview updates.
        """
        self.system.running = True

        # Create GUI
        self.gui = self.create_gui()

        # Initialize command handler with GUI reference
        if self.enable_commands:
            self.command_handler = self.create_command_handler(self.gui)
            self.logger.info("Starting GUI mode with parent command support")
        else:
            self.logger.info("Starting GUI mode (standalone)")

        # Start preview update task (if module implements it)
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

    async def _run_gui_async(self) -> None:
        """
        Run tkinter GUI in async context.

        Uses asyncio-friendly approach to run tkinter mainloop
        by calling update() periodically instead of blocking mainloop().
        """
        import tkinter as tk

        loop = asyncio.get_event_loop()
        window = self.get_gui_window()

        if not window:
            self.logger.error("No GUI window available")
            return

        def update_gui():
            """Update GUI and schedule next update."""
            try:
                if window.winfo_exists():
                    window.update()
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

        try:
            # Start GUI update loop
            loop.call_soon(update_gui)

            # Wait for shutdown
            await self.system.shutdown_event.wait()

        finally:
            # Destroy GUI
            if self.gui:
                try:
                    if hasattr(self.gui, 'destroy'):
                        self.gui.destroy()
                    elif window:
                        window.destroy()
                except Exception as e:
                    self.logger.debug("Error destroying GUI: %s", e)

    async def _preview_update_loop(self) -> None:
        """
        Async loop to update preview displays.

        Calls module-specific update_preview() at configured interval.
        """
        interval = self.get_preview_update_interval()
        window = self.get_gui_window()

        while self.is_running():
            try:
                # Update preview via module-specific implementation
                if window and window.winfo_exists():
                    # Schedule on main thread via tkinter
                    window.after(0, lambda: asyncio.create_task(self.update_preview()))

                await asyncio.sleep(interval)
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

        Wraps the standard command handler and ensures the GUI
        reflects changes made by commands from parent process.

        Args:
            command_data: Parsed command dict from JSON

        Returns:
            True to continue, False to shutdown (quit command received)
        """
        if not self.command_handler:
            self.logger.error("No command handler available")
            return True

        cmd = command_data.get("command")

        # Execute command via standard handler (returns False for quit command)
        continue_running = await self.command_handler.handle_command(command_data)

        if not continue_running:
            # Quit command received - trigger shutdown
            return False

        # Sync GUI state after command execution (thread-safe via window.after)
        window = self.get_gui_window()
        if window and window.winfo_exists():
            if cmd in ("start_recording", "stop_recording"):
                # Ensure GUI reflects recording state changes
                window.after(0, self.sync_recording_state)

        return True
