"""Base GPS Handler

Abstract base class defining the interface for all GPS device handlers.
Each GPS device gets its own handler instance managing parsing, logging,
and data callbacks.

Implements self-healing circuit breaker via ReconnectingMixin - instead of
permanently exiting after N consecutive errors, the handler will attempt
reconnection with exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from rpi_logger.core.connection import ReconnectingMixin, ReconnectConfig
from ..parsers.nmea_parser import NMEAParser
from ..parsers.nmea_types import GPSFixSnapshot
from ..transports import BaseGPSTransport
from ..data_logger import GPSDataLogger

logger = logging.getLogger(__name__)


def _task_exception_handler(task: asyncio.Task) -> None:
    """Handle exceptions from fire-and-forget tasks."""
    try:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Unhandled exception in GPS background task: %s", exc)
    except asyncio.CancelledError:
        pass


class BaseGPSHandler(ABC, ReconnectingMixin):
    """Abstract base class for GPS device handlers.

    Defines the common interface that all GPS handlers must implement.
    Handles device communication, NMEA parsing, and data logging.

    Each GPS device gets its own handler instance, enabling multi-instance
    support where multiple GPS receivers can be used simultaneously.

    Inherits ReconnectingMixin to provide self-healing circuit breaker behavior.
    Instead of permanently exiting after consecutive errors, the handler will
    attempt to reconnect with exponential backoff.
    """

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: BaseGPSTransport,
    ):
        """Initialize the handler.

        Args:
            device_id: Unique identifier for this device (e.g., "GPS:serial0")
            output_dir: Directory for data output files
            transport: Transport layer for device communication
        """
        self.device_id = device_id
        self.output_dir = output_dir
        self.transport = transport

        # NMEA parser
        self._parser = NMEAParser(
            on_fix_update=self._on_parser_update,
            validate_checksums=True,
        )

        # Data logger (created when recording starts)
        self._data_logger: Optional[GPSDataLogger] = None

        # Callback for data events (set by runtime)
        self.data_callback: Optional[Callable[[str, GPSFixSnapshot, Dict[str, Any]], Awaitable[None]]] = None

        # Internal state
        self._running = False
        self._recording = False
        self._read_task: Optional[asyncio.Task] = None
        self._trial_number: int = 1

        # Circuit breaker error tracking (used by ReconnectingMixin)
        self._consecutive_errors = 0

        # Initialize reconnection mixin for self-healing circuit breaker
        self._init_reconnect(
            device_id=device_id,
            config=ReconnectConfig.default(),
        )

        # Track pending background tasks for cleanup
        self._pending_tasks: Set[asyncio.Task] = set()

    @property
    def fix(self) -> GPSFixSnapshot:
        """Current GPS fix from the parser."""
        return self._parser.fix

    @property
    def is_connected(self) -> bool:
        """Check if the device transport is connected."""
        return self.transport.is_connected if self.transport else False

    @property
    def is_running(self) -> bool:
        """Check if the handler read loop is running."""
        return self._running

    @property
    def is_recording(self) -> bool:
        """Check if recording is active."""
        return self._recording

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def start(self) -> None:
        """Start the handler's read loop.

        This begins monitoring the device for incoming NMEA data.
        """
        if self._running:
            logger.warning("Handler %s already running", self.device_id)
            return

        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())
        logger.info("GPS handler started for %s", self.device_id)

    async def stop(self) -> None:
        """Stop the handler's read loop.

        This stops monitoring and cleans up resources.
        """
        self._running = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        # Cancel any pending background tasks
        for task in self._pending_tasks:
            if not task.done():
                task.cancel()
        self._pending_tasks.clear()

        # Stop recording if active
        if self._recording:
            self.stop_recording()

        logger.info("GPS handler stopped for %s", self.device_id)

    # =========================================================================
    # Recording Control
    # =========================================================================

    def start_recording(self, trial_number: int = 1) -> bool:
        """Start data recording.

        Args:
            trial_number: Trial number for the session

        Returns:
            True if recording started successfully
        """
        if self._recording:
            logger.debug("Recording already active for %s", self.device_id)
            return True

        self._trial_number = trial_number

        self._data_logger = GPSDataLogger(self.output_dir, self.device_id)
        path = self._data_logger.start_recording(trial_number)

        if path:
            self._recording = True
            logger.info("Started GPS recording for %s: %s", self.device_id, path)
            return True

        logger.error("Failed to start GPS recording for %s", self.device_id)
        self._data_logger = None
        return False

    def stop_recording(self) -> None:
        """Stop data recording."""
        if not self._recording:
            return

        if self._data_logger:
            self._data_logger.stop_recording()
            self._data_logger = None

        self._recording = False
        logger.info("Stopped GPS recording for %s", self.device_id)

    def update_trial_number(self, trial_number: int) -> None:
        """Update the trial number for subsequent records.

        Args:
            trial_number: New trial number
        """
        self._trial_number = trial_number
        if self._data_logger:
            self._data_logger.update_trial_number(trial_number)

    def update_output_dir(self, output_dir: Path) -> None:
        """Update the output directory for data logging.

        Args:
            output_dir: New output directory path
        """
        self.output_dir = output_dir
        if self._data_logger:
            self._data_logger.update_output_dir(output_dir)

    # =========================================================================
    # Read Loop
    # =========================================================================

    async def _read_loop(self) -> None:
        """Main read loop for receiving NMEA data.

        Continuously reads from the transport and processes sentences.
        Implements self-healing circuit breaker - instead of permanently exiting
        after N consecutive errors, attempts reconnection with exponential backoff.
        """
        logger.debug("Read loop started for %s", self.device_id)
        self._consecutive_errors = 0

        while self._running:
            # Check connection status - attempt reconnect if disconnected
            if not self.is_connected:
                logger.warning("GPS device %s disconnected, attempting reconnect", self.device_id)
                should_continue = await self._on_circuit_breaker_triggered()
                if not should_continue:
                    logger.error("Reconnection failed for %s - exiting read loop", self.device_id)
                    break
                continue

            try:
                # Read a line from the transport
                line = await self.transport.read_line(timeout=1.0)

                if line:
                    # Reset error counter on successful read
                    self._consecutive_errors = 0

                    # Process NMEA sentence
                    if line.startswith("$"):
                        self._process_sentence(line)

                # Yield to other tasks
                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_errors += 1
                config = self._reconnect_config
                backoff = min(
                    config.error_backoff * (2 ** (self._consecutive_errors - 1)),
                    config.max_error_backoff
                )
                logger.error(
                    "Error in GPS read loop for %s (%d/%d): %s",
                    self.device_id,
                    self._consecutive_errors,
                    config.max_consecutive_errors,
                    e
                )

                # Self-healing circuit breaker: attempt reconnection instead of hard exit
                if self._consecutive_errors >= config.max_consecutive_errors:
                    logger.warning(
                        "Circuit breaker triggered for %s - attempting reconnection",
                        self.device_id
                    )
                    should_continue = await self._on_circuit_breaker_triggered()
                    if not should_continue:
                        logger.error("Reconnection failed for %s - exiting read loop", self.device_id)
                        break
                    # Reconnected successfully, continue loop
                    continue

                await asyncio.sleep(backoff)

        logger.debug(
            "Read loop ended for %s (running=%s, connected=%s, errors=%d, reconnect_state=%s)",
            self.device_id,
            self._running,
            self.is_connected,
            self._consecutive_errors,
            self._reconnect_state.value if hasattr(self, '_reconnect_state') else 'N/A'
        )

    async def _attempt_reconnect(self) -> bool:
        """Attempt to reconnect the transport.

        This is called by ReconnectingMixin when circuit breaker triggers.
        Disconnects the transport and attempts to reconnect.

        Returns:
            True if reconnection succeeded, False otherwise
        """
        try:
            # First disconnect cleanly
            if self.transport:
                await self.transport.disconnect()

            # Brief delay to let the OS release the port
            await asyncio.sleep(0.2)

            # Attempt to reconnect
            if self.transport:
                success = await self.transport.connect()
                if success:
                    logger.info("GPS transport reconnected for %s", self.device_id)
                    return True
                else:
                    logger.warning("GPS transport reconnect failed for %s", self.device_id)
                    return False

            return False

        except Exception as e:
            logger.error("Error during GPS reconnect attempt for %s: %s", self.device_id, e)
            return False

    @abstractmethod
    def _process_sentence(self, sentence: str) -> None:
        """Process an NMEA sentence.

        Subclasses can override this to add device-specific processing.

        Args:
            sentence: Raw NMEA sentence
        """
        ...

    def _on_parser_update(self, fix: GPSFixSnapshot, update: Dict[str, Any]) -> None:
        """Called by the parser when fix is updated.

        Args:
            fix: Updated GPS fix
            update: Dictionary of changed values
        """
        # Log to CSV if recording
        if self._recording and self._data_logger:
            sentence_type = update.get("sentence_type", "")
            raw_sentence = update.get("raw_sentence", "")
            self._data_logger.log_fix(fix, sentence_type, raw_sentence)

        # Notify runtime via callback
        if self.data_callback:
            task = asyncio.create_task(
                self.data_callback(self.device_id, fix, update)
            )
            self._pending_tasks.add(task)
            task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        """Callback when a background task completes."""
        self._pending_tasks.discard(task)
        _task_exception_handler(task)

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _create_background_task(self, coro) -> asyncio.Task:
        """Create a tracked background task with exception handling.

        Args:
            coro: Coroutine to run

        Returns:
            The created task
        """
        task = asyncio.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task
