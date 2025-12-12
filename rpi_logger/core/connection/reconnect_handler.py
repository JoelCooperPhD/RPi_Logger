"""
Reconnect Handler - Self-healing connection pattern.

This module provides a mixin that adds auto-reconnect capability to handlers.
Instead of permanently exiting after N consecutive errors (hard circuit breaker),
handlers can attempt reconnection with exponential backoff.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Optional

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("ReconnectHandler")


class ReconnectState(Enum):
    """Current state of the reconnection process."""
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class ReconnectConfig:
    """Configuration for reconnection behavior."""
    # Circuit breaker thresholds
    max_consecutive_errors: int = 10
    error_backoff: float = 0.1
    max_error_backoff: float = 2.0

    # Reconnection settings
    max_reconnect_attempts: int = 5
    base_reconnect_delay: float = 1.0
    max_reconnect_delay: float = 30.0
    backoff_factor: float = 2.0

    # Jitter to prevent thundering herd
    jitter_factor: float = 0.1

    @classmethod
    def default(cls) -> "ReconnectConfig":
        """Get default configuration."""
        return cls()


@dataclass
class ReconnectResult:
    """Result of a reconnection attempt."""
    success: bool
    attempt: int
    total_attempts: int
    duration_ms: float
    error: Optional[str] = None


# Callback type for state change notifications
ReconnectStateCallback = Callable[[str, ReconnectState, int, int], Awaitable[None]]


class ReconnectingMixin:
    """
    Mixin that adds auto-reconnect capability to handlers.

    This replaces the hard circuit breaker pattern where handlers
    permanently exit after N consecutive errors. Instead, handlers
    will attempt to reconnect with exponential backoff.

    Usage:
        class MyHandler(BaseHandler, ReconnectingMixin):
            def __init__(self, ...):
                super().__init__(...)
                self._init_reconnect(config=ReconnectConfig.default())

            async def _attempt_reconnect(self) -> bool:
                # Implementation: try to reconnect transport
                await self.transport.disconnect()
                return await self.transport.connect()

    In your read loop, replace:
        if self._consecutive_errors >= self._max_consecutive_errors:
            break  # OLD: permanent exit

    With:
        if self._consecutive_errors >= self._reconnect_config.max_consecutive_errors:
            should_continue = await self._on_circuit_breaker_triggered()
            if not should_continue:
                break
            continue  # Reconnected, continue loop
    """

    # These are set by _init_reconnect
    _reconnect_config: ReconnectConfig
    _reconnect_state: ReconnectState
    _reconnect_attempt: int
    _reconnect_callback: Optional[ReconnectStateCallback]
    _reconnect_device_id: str

    def _init_reconnect(
        self,
        device_id: str,
        config: Optional[ReconnectConfig] = None,
        callback: Optional[ReconnectStateCallback] = None,
    ) -> None:
        """
        Initialize reconnection state.

        Args:
            device_id: Device identifier for logging/callbacks
            config: Reconnection configuration (uses default if not provided)
            callback: Optional async callback for state change notifications
        """
        self._reconnect_config = config or ReconnectConfig.default()
        self._reconnect_state = ReconnectState.CONNECTED
        self._reconnect_attempt = 0
        self._reconnect_callback = callback
        self._reconnect_device_id = device_id

    def set_reconnect_callback(
        self,
        callback: ReconnectStateCallback,
    ) -> None:
        """
        Set callback for reconnection state changes.

        Callback signature: async def callback(device_id, state, attempt, max_attempts)

        This is useful for updating UI status during reconnection.
        """
        self._reconnect_callback = callback

    async def _on_circuit_breaker_triggered(self) -> bool:
        """
        Called when circuit breaker threshold is reached.

        Instead of exiting permanently, this attempts reconnection
        with exponential backoff.

        Returns:
            True if reconnected and should continue, False if should exit
        """
        import random
        import time

        config = self._reconnect_config

        if self._reconnect_attempt >= config.max_reconnect_attempts:
            # Exhausted all reconnection attempts
            self._reconnect_state = ReconnectState.FAILED
            await self._notify_reconnect_state()
            logger.error(
                "Reconnection failed for %s after %d attempts - giving up",
                self._reconnect_device_id,
                self._reconnect_attempt,
            )
            return False

        # Enter reconnecting state
        self._reconnect_state = ReconnectState.RECONNECTING
        self._reconnect_attempt += 1
        await self._notify_reconnect_state()

        # Calculate backoff delay with jitter
        delay = min(
            config.base_reconnect_delay * (config.backoff_factor ** (self._reconnect_attempt - 1)),
            config.max_reconnect_delay,
        )
        jitter = delay * config.jitter_factor * random.random()
        delay += jitter

        logger.info(
            "Circuit breaker triggered for %s - attempting reconnect %d/%d in %.1fs",
            self._reconnect_device_id,
            self._reconnect_attempt,
            config.max_reconnect_attempts,
            delay,
        )

        await asyncio.sleep(delay)

        # Attempt reconnection
        start_time = time.perf_counter()
        try:
            success = await self._attempt_reconnect()
            duration_ms = (time.perf_counter() - start_time) * 1000

            if success:
                # Reconnection successful - reset state
                self._reconnect_state = ReconnectState.CONNECTED
                self._reconnect_attempt = 0
                # Reset error counter (subclass should have this)
                if hasattr(self, '_consecutive_errors'):
                    self._consecutive_errors = 0
                await self._notify_reconnect_state()

                logger.info(
                    "Reconnected %s successfully in %.1fms (attempt %d)",
                    self._reconnect_device_id,
                    duration_ms,
                    self._reconnect_attempt,
                )
                return True
            else:
                logger.warning(
                    "Reconnection attempt %d failed for %s (%.1fms)",
                    self._reconnect_attempt,
                    self._reconnect_device_id,
                    duration_ms,
                )
                # Try again
                return await self._on_circuit_breaker_triggered()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "Reconnection attempt %d failed for %s: %s (%.1fms)",
                self._reconnect_attempt,
                self._reconnect_device_id,
                e,
                duration_ms,
            )
            # Try again
            return await self._on_circuit_breaker_triggered()

    async def _attempt_reconnect(self) -> bool:
        """
        Attempt to reconnect the transport.

        Subclasses MUST override this method to implement actual reconnection.

        Returns:
            True if reconnection succeeded, False otherwise
        """
        raise NotImplementedError(
            "Subclass must implement _attempt_reconnect() to use ReconnectingMixin"
        )

    async def _notify_reconnect_state(self) -> None:
        """Notify callback of state change."""
        if self._reconnect_callback:
            try:
                await self._reconnect_callback(
                    self._reconnect_device_id,
                    self._reconnect_state,
                    self._reconnect_attempt,
                    self._reconnect_config.max_reconnect_attempts,
                )
            except Exception as e:
                logger.error("Reconnect callback error: %s", e)

    @property
    def reconnect_state(self) -> ReconnectState:
        """Get current reconnection state."""
        return self._reconnect_state

    @property
    def is_reconnecting(self) -> bool:
        """Check if currently attempting reconnection."""
        return self._reconnect_state == ReconnectState.RECONNECTING

    @property
    def reconnect_failed(self) -> bool:
        """Check if reconnection has permanently failed."""
        return self._reconnect_state == ReconnectState.FAILED

    def reset_reconnect_state(self) -> None:
        """Reset reconnection state (e.g., after manual reconnect)."""
        self._reconnect_state = ReconnectState.CONNECTED
        self._reconnect_attempt = 0
        if hasattr(self, '_consecutive_errors'):
            self._consecutive_errors = 0
