"""
Base DRT Handler

Abstract base class defining the interface for all DRT device handlers.
Each device type (sDRT, wDRT USB, wDRT Wireless) implements this interface
with their specific protocol.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable, Awaitable
from pathlib import Path
import asyncio
import logging

from ..device_types import DRTDeviceType

logger = logging.getLogger(__name__)


class BaseDRTHandler(ABC):
    """
    Abstract base class for DRT device handlers.

    Defines the common interface that all DRT handlers must implement.
    Handles device communication, experiment control, and data logging.
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

        # Circuit breaker for error recovery
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10  # Trigger disconnect after this many errors
        self._error_backoff = 0.1  # Initial backoff in seconds
        self._max_error_backoff = 2.0  # Maximum backoff

        # Trial data tracking
        self._click_count = 0
        self._trial_number = 0
        self._buffered_trial_data: Optional[Dict[str, Any]] = None
        self._trial_label: str = ""  # Condition/experiment label for CSV output

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

    @property
    def circuit_breaker_tripped(self) -> bool:
        """Check if the circuit breaker has been triggered due to errors."""
        return self._consecutive_errors >= self._max_consecutive_errors

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def start(self) -> None:
        """
        Start the handler's read loop.

        This begins monitoring the device for incoming data.
        """
        if self._running:
            logger.warning(f"Handler {self.device_id} already running")
            return

        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())
        logger.info(f"Handler started for {self.device_id}")

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

        logger.info(f"Handler stopped for {self.device_id}")

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
    # Data Logging (Abstract)
    # =========================================================================

    @abstractmethod
    def _log_trial_data(self, data: Dict[str, Any]) -> None:
        """
        Log trial data to CSV file.

        Args:
            data: Trial data dictionary
        """
        ...

    @abstractmethod
    def _get_csv_header(self) -> str:
        """
        Return the CSV header for this device type.

        Returns:
            CSV header string
        """
        ...

    # =========================================================================
    # Common Implementation
    # =========================================================================

    async def _read_loop(self) -> None:
        """
        Main read loop for receiving device data.

        Continuously reads from the transport and processes responses.
        Implements circuit breaker pattern - exits after too many consecutive errors.
        """
        logger.debug(f"Read loop started for {self.device_id}")
        self._consecutive_errors = 0

        while self._running and self.is_connected:
            try:
                # Process all available data in the buffer
                lines_processed = 0
                while lines_processed < 50:  # Limit to prevent infinite loop
                    line = await self.transport.read_line()
                    if line:
                        logger.debug(f"Processing line from {self.device_id}: {line.strip()}")
                        self._process_response(line.strip())
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
                backoff = min(
                    self._error_backoff * (2 ** (self._consecutive_errors - 1)),
                    self._max_error_backoff
                )
                logger.error(
                    f"Error in read loop for {self.device_id} "
                    f"({self._consecutive_errors}/{self._max_consecutive_errors}): {e}"
                )

                # Circuit breaker: exit if too many consecutive errors
                if self._consecutive_errors >= self._max_consecutive_errors:
                    logger.error(
                        f"Circuit breaker triggered for {self.device_id}: "
                        f"{self._consecutive_errors} consecutive errors. "
                        f"Handler will be marked as disconnected."
                    )
                    break

                await asyncio.sleep(backoff)

        logger.debug(
            f"Read loop ended for {self.device_id} "
            f"(running={self._running}, connected={self.is_connected}, "
            f"errors={self._consecutive_errors})"
        )

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
                logger.error(f"Error in data callback: {e}")

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
