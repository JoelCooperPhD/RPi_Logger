#!/usr/bin/env python3
"""
Base Mode - Unified base class for operational modes.

Provides common functionality for:
- Mode lifecycle management
- System reference
- Running state checking
- Logging
"""

import logging
from abc import ABC, abstractmethod
from typing import Any


class BaseMode(ABC):
    """
    Abstract base class for operational modes.

    All module modes (GUI, Headless, Slave) should inherit from this class.
    Provides common patterns for mode execution and system interaction.
    """

    def __init__(self, system: Any):
        """
        Initialize base mode.

        Args:
            system: Reference to system instance (AudioSystem, CameraSystem, TrackerSystem)
        """
        self.system = system
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    async def run(self) -> None:
        """
        Run the mode.

        Subclasses must implement this to provide mode-specific behavior.
        This is the main entry point for mode execution.

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement run()")

    def is_running(self) -> bool:
        """
        Check if system is still running.

        Returns:
            True if system is running and not shutting down, False otherwise
        """
        return (
            getattr(self.system, 'running', True) and
            not getattr(self.system, 'shutdown_event', None) or
            not self.system.shutdown_event.is_set()
        )
