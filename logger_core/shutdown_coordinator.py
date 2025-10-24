"""
Shutdown Coordinator - Single point of control for graceful shutdown.

This module provides centralized shutdown coordination to prevent race
conditions and ensure clean teardown of all system components.
"""

import asyncio
import logging
from enum import Enum
from typing import Optional, Callable, Awaitable


class ShutdownState(Enum):
    """States of the shutdown process."""
    RUNNING = "running"
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


class ShutdownCoordinator:
    """
    Coordinates shutdown across all components.

    Ensures that shutdown only happens once and that all cleanup
    operations complete in the correct order.

    Shutdown sequence:
    1. User/signal triggers shutdown via initiate_shutdown()
    2. State transitions to REQUESTED
    3. Cleanup callbacks are executed in order
    4. State transitions to IN_PROGRESS
    5. Final cleanup completes
    6. State transitions to COMPLETE
    """

    def __init__(self):
        self.logger = logging.getLogger("ShutdownCoordinator")
        self._state = ShutdownState.RUNNING
        self._shutdown_event = asyncio.Event()
        self._cleanup_callbacks: list[Callable[[], Awaitable[None]]] = []
        self._lock = asyncio.Lock()

    @property
    def state(self) -> ShutdownState:
        """Get current shutdown state."""
        return self._state

    @property
    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress or requested."""
        return self._state in (ShutdownState.REQUESTED, ShutdownState.IN_PROGRESS)

    @property
    def is_complete(self) -> bool:
        """Check if shutdown is complete."""
        return self._state == ShutdownState.COMPLETE

    def register_cleanup(self, callback: Callable[[], Awaitable[None]]) -> None:
        """
        Register a cleanup callback to be executed during shutdown.

        Callbacks are executed in the order they are registered.

        Args:
            callback: Async function to call during shutdown
        """
        self._cleanup_callbacks.append(callback)
        self.logger.debug("Registered cleanup callback: %s", callback.__name__)

    async def initiate_shutdown(self, source: str = "unknown") -> None:
        """
        Initiate graceful shutdown.

        This is the single entry point for all shutdown requests.
        If shutdown is already in progress, this call is a no-op.

        Args:
            source: Description of what triggered shutdown (for logging)
        """
        async with self._lock:
            if self._state != ShutdownState.RUNNING:
                self.logger.debug("Shutdown already initiated (state=%s), ignoring request from %s",
                                self._state.value, source)
                return

            self.logger.info("=" * 60)
            self.logger.info("Shutdown initiated by: %s", source)
            self.logger.info("=" * 60)
            self._state = ShutdownState.REQUESTED

        # Execute cleanup callbacks
        await self._execute_cleanup()

        # Mark shutdown complete
        async with self._lock:
            self._state = ShutdownState.COMPLETE
            self._shutdown_event.set()

        self.logger.info("Shutdown complete")

    async def _execute_cleanup(self) -> None:
        """Execute all registered cleanup callbacks."""
        async with self._lock:
            self._state = ShutdownState.IN_PROGRESS

        self.logger.info("Running %d cleanup callbacks...", len(self._cleanup_callbacks))

        for i, callback in enumerate(self._cleanup_callbacks, 1):
            try:
                self.logger.debug("Cleanup %d/%d: %s",
                                i, len(self._cleanup_callbacks), callback.__name__)
                await callback()
            except Exception as e:
                self.logger.error("Error in cleanup callback %s: %s",
                                callback.__name__, e, exc_info=True)

        self.logger.info("All cleanup callbacks complete")

    async def wait_for_shutdown(self) -> None:
        """
        Wait until shutdown is complete.

        Useful for components that need to block until shutdown finishes.
        """
        await self._shutdown_event.wait()


# Global singleton instance
_coordinator: Optional[ShutdownCoordinator] = None


def get_shutdown_coordinator() -> ShutdownCoordinator:
    """Get the global shutdown coordinator instance."""
    global _coordinator
    if _coordinator is None:
        _coordinator = ShutdownCoordinator()
    return _coordinator


def reset_shutdown_coordinator() -> None:
    """Reset the global coordinator (mainly for testing)."""
    global _coordinator
    _coordinator = None
