#!/usr/bin/env python3
"""
Base mode class for audio recording system.

Provides common functionality for all operational modes.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class BaseMode:
    """Base class for operational modes."""

    def __init__(self, audio_system: 'AudioSystem'):
        """
        Initialize base mode.

        Args:
            audio_system: Audio system instance
        """
        self.system = audio_system
        self.logger = logging.getLogger(self.__class__.__name__)

    def is_running(self) -> bool:
        """
        Check if system is still running.

        Returns:
            True if system is running and not shutting down
        """
        return self.system.running and not self.system.shutdown_event.is_set()

    async def run(self) -> None:
        """
        Run the mode (must be implemented by subclass).

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement run()")
