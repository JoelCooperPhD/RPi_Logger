"""Base GPS Handler with self-healing circuit breaker.

Abstract interface for GPS device handlers managing parsing, logging, and callbacks.
Uses ReconnectingMixin for automatic reconnection with exponential backoff.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from rpi_logger.core.connection import ReconnectingMixin, ReconnectConfig
from rpi_logger.core.logging_utils import get_module_logger
from ..constants import DEFAULT_STALE_THRESHOLD
from ..parsers.nmea_parser import NMEAParser
from ..parsers.nmea_types import GPSFixSnapshot
from ..transports import BaseGPSTransport
from ..data_logger import GPSDataLogger

logger = get_module_logger(__name__)


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
    """Abstract base for GPS handlers with multi-instance support and auto-reconnection."""

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: BaseGPSTransport,
        stale_threshold: float = DEFAULT_STALE_THRESHOLD,
    ):
        """Initialize handler with device ID, output directory, and transport."""
        self.device_id = device_id
        self.output_dir = output_dir
        self.transport = transport
        self._stale_threshold = stale_threshold

        self._parser = NMEAParser(on_fix_update=self._on_parser_update, validate_checksums=True)
        self._data_logger: Optional[GPSDataLogger] = None
        self.data_callback: Optional[Callable[[str, GPSFixSnapshot, Dict[str, Any]], Awaitable[None]]] = None
        self._running = False
        self._recording = False
        self._read_task: Optional[asyncio.Task] = None
        self._trial_number: int = 1
        self._consecutive_errors = 0
        self._logged_stale = False
        self._init_reconnect(device_id=device_id, config=ReconnectConfig.default())
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

    async def start(self) -> None:
        """Start read loop to monitor device for NMEA data."""
        if self._running:
            logger.info("Handler %s already running", self.device_id)
            return

        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())
        logger.info("GPS handler started for %s", self.device_id)

    async def stop(self) -> None:
        """Stop read loop and clean up resources."""
        self._running = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        for task in self._pending_tasks:
            if not task.done():
                task.cancel()
        self._pending_tasks.clear()

        if self._recording:
            self.stop_recording()

        logger.info("GPS handler stopped for %s", self.device_id)

    def start_recording(self, trial_number: int = 1, trial_label: str = "") -> bool:
        """Start data recording. Returns True if successful."""
        if self._recording:
            logger.debug("Recording already active for %s", self.device_id)
            return True

        self._trial_number = trial_number

        self._data_logger = GPSDataLogger(self.output_dir, self.device_id)
        path = self._data_logger.start_recording(trial_number, trial_label)

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
        """Update trial number for subsequent records."""
        self._trial_number = trial_number
        if self._data_logger:
            self._data_logger.update_trial_number(trial_number)

    def update_output_dir(self, output_dir: Path) -> None:
        """Update output directory for data logging."""
        self.output_dir = output_dir
        if self._data_logger:
            self._data_logger.update_output_dir(output_dir)

    async def _read_loop(self) -> None:
        """Read loop with self-healing circuit breaker and exponential backoff."""
        logger.debug("Read loop started for %s", self.device_id)
        self._consecutive_errors = 0

        while self._running:
            if not self.is_connected:
                logger.warning("GPS device %s disconnected, attempting reconnect", self.device_id)
                if not await self._on_circuit_breaker_triggered():
                    logger.error("Reconnection failed for %s - exiting read loop", self.device_id)
                    break
                continue

            try:
                line = await self.transport.read_line(timeout=1.0)
                if line:
                    self._consecutive_errors = 0
                    self._logged_stale = False
                    if line.startswith("$"):
                        self._process_sentence(line)

                self._check_staleness()
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
                logger.warning(
                    "Error in GPS read loop for %s (%d/%d): %s",
                    self.device_id, self._consecutive_errors, config.max_consecutive_errors, e
                )

                if self._consecutive_errors >= config.max_consecutive_errors:
                    logger.warning("Circuit breaker triggered for %s - attempting reconnection", self.device_id)
                    if not await self._on_circuit_breaker_triggered():
                        logger.error("Reconnection failed for %s - exiting read loop", self.device_id)
                        break
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
        """Reconnect transport. Called by ReconnectingMixin on circuit breaker trigger."""
        try:
            if self.transport:
                await self.transport.disconnect()
            await asyncio.sleep(0.2)
            if self.transport:
                success = await self.transport.connect()
                if success:
                    logger.info("GPS transport reconnected for %s", self.device_id)
                else:
                    logger.warning("GPS transport reconnect failed for %s", self.device_id)
                return success
            return False
        except Exception as e:
            logger.error("Error during GPS reconnect attempt for %s: %s", self.device_id, e)
            return False

    def _check_staleness(self) -> None:
        """Invalidate fix if no valid data received within threshold."""
        fix = self._parser.fix
        age = fix.age_seconds()
        if age is not None and age > self._stale_threshold and fix.fix_valid:
            fix.fix_valid = False
            if not self._logged_stale:
                self._logged_stale = True
                logger.warning(
                    "GPS %s data stale (%.1fs without valid NMEA) - fix invalidated",
                    self.device_id, age
                )

    @abstractmethod
    def _process_sentence(self, sentence: str) -> None:
        """Process NMEA sentence. Override for device-specific processing."""
        ...

    def _on_parser_update(self, fix: GPSFixSnapshot, update: Dict[str, Any]) -> None:
        """Called when parser updates fix."""
        if self._recording and self._data_logger:
            self._data_logger.log_fix(fix, update.get("sentence_type", ""), update.get("raw_sentence", ""))
        if self.data_callback:
            self._create_background_task(self.data_callback(self.device_id, fix, update))

    def _on_task_done(self, task: asyncio.Task) -> None:
        """Callback when background task completes."""
        self._pending_tasks.discard(task)
        _task_exception_handler(task)

    def _create_background_task(self, coro) -> Optional[asyncio.Task]:
        """Create tracked background task with exception handling."""
        try:
            task = asyncio.create_task(coro)
            self._pending_tasks.add(task)
            task.add_done_callback(self._on_task_done)
            return task
        except RuntimeError:
            # No running event loop (e.g., in tests or sync context)
            coro.close()
            return None
