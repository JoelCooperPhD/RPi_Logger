#!/usr/bin/env python3
"""
Base System - Abstract base class for module systems.

Provides common functionality for:
- System initialization
- Mode selection and execution
- Session management
- Shutdown handling
- Device discovery patterns
"""

import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional


class BaseSystem(ABC):
    """
    Abstract base class for module systems.

    Provides common patterns for initialization, mode management,
    and shutdown handling. Subclasses implement device-specific logic.
    """

    def __init__(self, args: Any):
        """
        Initialize base system.

        Args:
            args: Parsed command line arguments
        """
        self.args = args
        self.logger = logging.getLogger(self.__class__.__name__)
        self.running = False
        self.recording = False
        self.shutdown_event = asyncio.Event()
        self.initialized = False

        # Mode configuration
        self.mode = getattr(args, "mode", "gui")
        self.slave_mode = self.mode == "slave"
        self.headless_mode = self.mode == "headless"
        self.gui_mode = self.mode == "gui"

        # Session management
        self.session_dir: Optional[Path] = getattr(args, "session_dir", None)
        if self.session_dir:
            self.session_label = self.session_dir.name
            self.logger.info("Session directory: %s", self.session_dir)

        # Console output (for user-facing messages in slave mode)
        self.console = getattr(args, "console_stdout", sys.stdout)

        # Device discovery settings
        self.device_timeout = getattr(args, "discovery_timeout", 5.0)

    @abstractmethod
    async def _initialize_devices(self) -> None:
        """
        Initialize devices/hardware.

        Subclasses must implement device-specific initialization logic.
        This should:
        - Discover available devices
        - Perform timeout-based retry
        - Set self.initialized = True on success
        - Raise InitializationError on failure

        Raises:
            InitializationError: If devices cannot be initialized
        """
        pass

    @abstractmethod
    def _create_mode_instance(self, mode_name: str) -> Any:
        """
        Create mode instance based on mode name.

        Subclasses must implement mode creation logic.

        Args:
            mode_name: Mode name ('gui', 'headless', 'slave')

        Returns:
            Mode instance
        """
        pass

    async def run(self) -> None:
        """
        Main run method - delegates to appropriate mode.

        This is the main entry point for the system.
        It handles initialization, mode selection, and execution.
        """
        try:
            # Initialize devices
            await self._initialize_devices()

            # Create and run appropriate mode
            mode_instance = self._create_mode_instance(self.mode)
            await mode_instance.run()

        except KeyboardInterrupt:
            self.logger.info("%s cancelled by user", self.__class__.__name__)
            if self.slave_mode:
                self._send_slave_error("Cancelled by user")
            raise
        except Exception as e:
            self.logger.error("Unexpected error in run: %s", e)
            if self.slave_mode:
                self._send_slave_error(f"Unexpected error: {e}")
            raise

    @abstractmethod
    async def cleanup(self) -> None:
        """
        Clean up system resources.

        Subclasses must implement cleanup logic for their devices/handlers.
        This should:
        - Stop any recording
        - Release device resources
        - Set self.running = False
        - Set self.initialized = False
        """
        pass

    def _send_slave_error(self, message: str) -> None:
        """
        Send error message in slave mode.

        Helper method to send error status messages.

        Args:
            message: Error message to send
        """
        try:
            from logger_core.commands import StatusMessage
            StatusMessage.send("error", {"message": message})
        except ImportError:
            self.logger.warning("Cannot send slave error - StatusMessage not available")

    def _send_slave_status(self, status: str, data: Optional[dict] = None) -> None:
        """
        Send status message in slave mode.

        Helper method to send status messages.

        Args:
            status: Status type
            data: Optional status data
        """
        if self.slave_mode:
            try:
                from logger_core.commands import StatusMessage
                StatusMessage.send(status, data or {})
            except ImportError:
                self.logger.warning("Cannot send slave status - StatusMessage not available")
