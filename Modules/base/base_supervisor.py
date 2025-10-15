#!/usr/bin/env python3
"""
Base Supervisor - Abstract supervisor for module systems.

Provides common functionality for:
- System lifecycle management
- Automatic retry on hardware failures
- Graceful shutdown handling
- Error recovery
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, Optional, Type, TypeVar

# Type variable for the system class
SystemT = TypeVar('SystemT')
# Type variable for the initialization error class
ErrorT = TypeVar('ErrorT', bound=Exception)


class BaseSupervisor(ABC, Generic[SystemT, ErrorT]):
    """
    Abstract base class for module supervisors.

    Supervisors maintain system availability with automatic retry on failures.
    Subclasses must implement system creation and specify error types.
    """

    def __init__(self, args: Any, default_retry_interval: float = 3.0):
        """
        Initialize supervisor.

        Args:
            args: Parsed command line arguments
            default_retry_interval: Default retry interval in seconds
        """
        self.args = args
        self.logger = logging.getLogger(self.__class__.__name__)
        self.retry_interval = getattr(args, "discovery_retry", default_retry_interval)
        self.shutdown_event = asyncio.Event()
        self.system: Optional[SystemT] = None

    @abstractmethod
    def create_system(self) -> SystemT:
        """
        Create system instance.

        Subclasses must implement this to instantiate their specific system.

        Returns:
            System instance (e.g., AudioSystem, CameraSystem, TrackerSystem)
        """
        pass

    @abstractmethod
    def get_initialization_error_type(self) -> Type[ErrorT]:
        """
        Get the initialization error type to catch for retry.

        Subclasses must return their specific initialization error class.

        Returns:
            Exception class (e.g., AudioInitializationError)
        """
        pass

    def get_system_name(self) -> str:
        """
        Get human-readable system name for logging.

        Default implementation extracts name from class name.
        Subclasses can override for custom names.

        Returns:
            System name (e.g., "Audio", "Camera", "Tracker")
        """
        # Extract from class name: "AudioSupervisor" -> "Audio"
        class_name = self.__class__.__name__
        return class_name.replace('Supervisor', '')

    async def run(self) -> None:
        """
        Run system with automatic retry on failure.

        This is the main entry point for the supervisor.
        It handles system lifecycle, error recovery, and shutdown.
        """
        system_name = self.get_system_name()
        initialization_error = self.get_initialization_error_type()

        while not self.shutdown_event.is_set():
            system = self.create_system()
            self.system = system

            try:
                await system.run()

            except initialization_error:
                # Hardware not available - retry
                if self.shutdown_event.is_set():
                    break
                self.logger.info(
                    "%s hardware not available; retrying in %.1fs",
                    system_name,
                    self.retry_interval,
                )
                await asyncio.sleep(self.retry_interval)
                continue

            except KeyboardInterrupt:
                self.logger.info("%s system interrupted", system_name)
                break

            except Exception as exc:  # pragma: no cover - defensive
                # Unexpected error - log and retry
                if self.shutdown_event.is_set():
                    break
                self.logger.exception("%s system crashed: %s", system_name, exc)
                await asyncio.sleep(self.retry_interval)
                continue

            finally:
                # Always cleanup system
                try:
                    await system.cleanup()
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.error("%s cleanup failed: %s", system_name, exc)
                self.system = None

            # Reaching here means run() completed normally; exit supervisor
            break

        self.logger.debug("%s supervisor exiting", system_name)

    async def shutdown(self) -> None:
        """
        Shutdown the supervisor and system.

        This sets shutdown events and triggers graceful shutdown.
        Safe to call multiple times.
        """
        if self.shutdown_event.is_set():
            return

        self.shutdown_event.set()

        # Signal system to shutdown if it exists
        system = self.system
        if system and hasattr(system, 'shutdown_event'):
            system.shutdown_event.set()
