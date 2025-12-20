"""
Base DRT Handler

Abstract base class defining the interface for all DRT device handlers.
Each device type (sDRT, wDRT USB, wDRT Wireless) implements this interface
with their specific protocol.

Implements self-healing circuit breaker via ReconnectingMixin - instead of
permanently exiting after N consecutive errors, the handler will attempt
reconnection with exponential backoff.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable, Awaitable, Set
from pathlib import Path
import asyncio
import logging

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.connection import ReconnectingMixin, ReconnectConfig
from ..device_types import DRTDeviceType

logger = get_module_logger(__name__)


def _task_exception_handler(task: asyncio.Task) -> None:
    """Handle exceptions from fire-and-forget tasks."""
    try:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Unhandled exception in background task: %s", exc)
    except asyncio.CancelledError:
        pass


class BaseDRTHandler(ABC, ReconnectingMixin):
    """
    Abstract base class for DRT device handlers.

    Defines the common interface that all DRT handlers must implement.
    Handles device communication, experiment control, and data logging.

    Inherits ReconnectingMixin to provide self-healing circuit breaker behavior.
    Instead of permanently exiting after consecutive errors, the handler will
    attempt to reconnect with exponential backoff.
    """

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: Any  # BaseTransport - avoiding circular import
    ):
        """
        Initialize the handler.

        Args:
            device_id: Unique identifier for this device (e.g., port name or XBee node ID)
            output_dir: Directory for data output files
            transport: Transport layer for device communication
        """
        self.device_id = device_id
        self.output_dir = output_dir
        self.transport = transport

        # Callback for data events (set by system)
        self.data_callback: Optional[Callable[[str, str, Dict[str, Any]], Awaitable[None]]] = None

        # Internal state
        self._running = False
        self._recording = False
        self._read_task: Optional[asyncio.Task] = None

        # Circuit breaker error tracking (used by ReconnectingMixin)
        self._consecutive_errors = 0

        # Initialize reconnection mixin for self-healing circuit breaker
        self._init_reconnect(
            device_id=device_id,
            config=ReconnectConfig.default(),
        )

        # Trial data tracking
        self._click_count = 0
        self._trial_number = 0
        self._buffered_trial_data: Optional[Dict[str, Any]] = None
        self._trial_label: str = ""  # Condition/experiment label for CSV output
        self._active_trial_number: int = 1

        # Track pending background tasks for cleanup
        self._pending_tasks: Set[asyncio.Task] = set()

    @property
    @abstractmethod
    def device_type(self) -> DRTDeviceType:
        """Return the device type for this handler."""
        ...

    @property
    def is_connected(self) -> bool:
        """Check if the device is connected."""
        return self.transport.is_connected if self.transport else False

    @property
    def is_running(self) -> bool:
        """Check if the handler read loop is running."""
        return self._running

    @property
    def is_recording(self) -> bool:
        """Check if recording is active."""
        return self._recording

    def set_active_trial_number(self, trial_number: int) -> None:
        """Set the active trial number for file naming."""
        try:
            value = int(trial_number)
        except (TypeError, ValueError):
            value = 1
        if value <= 0:
            value = 1
        self._active_trial_number = value

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def start(self) -> None:
        """
        Start the handler's read loop.

        This begins monitoring the device for incoming data.
        """
        if self._running:
            logger.warning("Handler %s already running", self.device_id)
            return

        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())
        logger.info("Handler started for %s", self.device_id)

    async def stop(self) -> None:
        """
        Stop the handler's read loop.

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

        logger.info("Handler stopped for %s", self.device_id)

    # =========================================================================
    # Command Methods (Abstract)
    # =========================================================================

    @abstractmethod
    async def send_command(self, command: str, value: Optional[str] = None) -> bool:
        """
        Send a command to the device.

        Args:
            command: Command key from the protocol commands dict
            value: Optional value to send with the command

        Returns:
            True if command was sent successfully
        """
        ...

    @abstractmethod
    async def start_experiment(self) -> bool:
        """
        Start the experiment/recording on the device.

        Returns:
            True if experiment started successfully
        """
        ...

    @abstractmethod
    async def stop_experiment(self) -> bool:
        """
        Stop the experiment/recording on the device.

        Returns:
            True if experiment stopped successfully
        """
        ...

    @abstractmethod
    async def set_stimulus(self, on: bool) -> bool:
        """
        Turn stimulus on or off.

        Args:
            on: True to turn stimulus on, False to turn off

        Returns:
            True if command was sent successfully
        """
        ...

    @abstractmethod
    async def get_config(self) -> Optional[Dict[str, Any]]:
        """
        Request and return device configuration.

        Returns:
            Configuration dict, or None if failed
        """
        ...

    # =========================================================================
    # Response Processing (Abstract)
    # =========================================================================

    @abstractmethod
    def _process_response(self, line: str) -> None:
        """
        Process a response line from the device.

        Args:
            line: Raw response line from the device
        """
        ...

    # =========================================================================
    # Common Implementation
    # =========================================================================

    async def _read_loop(self) -> None:
        """
        Main read loop for receiving device data.

        Continuously reads from the transport and processes responses.
        Implements self-healing circuit breaker - instead of permanently exiting
        after N consecutive errors, attempts reconnection with exponential backoff.
        """
        logger.debug("Read loop started for %s", self.device_id)
        self._consecutive_errors = 0

        while self._running:
            # Check connection status - attempt reconnect if disconnected
            if not self.is_connected:
                logger.warning("Device %s disconnected, attempting reconnect", self.device_id)
                should_continue = await self._on_circuit_breaker_triggered()
                if not should_continue:
                    logger.error("Reconnection failed for %s - exiting read loop", self.device_id)
                    break
                continue

            try:
                # Process all available data in the buffer
                lines_processed = 0
                while lines_processed < 50:  # Limit to prevent infinite loop
                    line = await self.transport.read_line()
                    if line:
                        stripped = line.strip()
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("Processing line from %s: %s", self.device_id, stripped)
                        self._process_response(stripped)
                        lines_processed += 1
                    else:
                        break

                # Reset error counter on successful iteration
                if lines_processed > 0:
                    self._consecutive_errors = 0

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
                    "Error in read loop for %s (%d/%d): %s",
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
        """
        Attempt to reconnect the transport.

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
                    logger.info("Transport reconnected for %s", self.device_id)
                    return True
                else:
                    logger.warning("Transport reconnect failed for %s", self.device_id)
                    return False

            return False

        except Exception as e:
            logger.error("Error during reconnect attempt for %s: %s", self.device_id, e)
            return False

    def _create_background_task(self, coro) -> asyncio.Task:
        """
        Create a tracked background task with exception handling.

        Args:
            coro: Coroutine to run

        Returns:
            The created task
        """
        task = asyncio.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task) -> None:
        """Callback when a background task completes."""
        self._pending_tasks.discard(task)
        _task_exception_handler(task)

    async def _dispatch_data_event(
        self,
        data_type: str,
        data: Dict[str, Any]
    ) -> None:
        """
        Dispatch a data event to the callback.

        Args:
            data_type: Type of data event (e.g., 'click', 'trial', 'stimulus')
            data: Event data dictionary
        """
        if self.data_callback:
            try:
                await self.data_callback(self.device_id, data_type, data)
            except Exception as e:
                logger.error("Error in data callback: %s", e)

    def set_recording_state(self, recording: bool, trial_label: str = "") -> None:
        """
        Set the recording state.

        Args:
            recording: True if recording is active
            trial_label: Condition/experiment label for CSV output
        """
        self._recording = recording
        self._trial_label = trial_label if recording else ""
        if recording:
            self._click_count = 0
            self._trial_number = 0
            self._buffered_trial_data = None

    def update_output_dir(self, output_dir: Path) -> None:
        """
        Update the output directory for data logging.

        Args:
            output_dir: New output directory path
        """
        self.output_dir = output_dir
        # Subclasses should override _update_data_logger_output_dir if they have a data logger
        self._update_data_logger_output_dir(output_dir)

    def _update_data_logger_output_dir(self, output_dir: Path) -> None:
        """Hook for subclasses to update their data logger's output directory."""
        pass
