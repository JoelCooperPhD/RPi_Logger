"""
sDRT Handler

Protocol handler for sDRT (Simple Detection Response Task) devices.
Handles USB serial communication with sDRT-specific command/response protocol.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import logging

from .base_handler import BaseDRTHandler
from ..device_types import DRTDeviceType
from ..transports import USBTransport
from ..protocols import (
    SDRT_COMMANDS,
    SDRT_RESPONSES,
    SDRT_LINE_ENDING,
    SDRT_CSV_HEADER,
    SDRT_ISO_PRESET,
    RESPONSE_DELIMITER,
    RT_TIMEOUT_VALUE,
)

logger = logging.getLogger(__name__)


class SDRTHandler(BaseDRTHandler):
    """
    Handler for sDRT devices.

    Implements the sDRT-specific protocol for experiment control,
    stimulus management, and data logging.
    """

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: USBTransport
    ):
        """
        Initialize the sDRT handler.

        Args:
            device_id: Unique identifier (typically the serial port)
            output_dir: Directory for CSV data files
            transport: USB transport for device communication
        """
        super().__init__(device_id, output_dir, transport)

        # Config future for async config retrieval
        self._config_future: Optional[asyncio.Future] = None

        # Track stimulus state
        self._stimulus_on = False

        # Track device's cumulative click count separately from per-trial count
        # Device sends cumulative counts; we calculate per-trial by tracking delta
        self._device_click_count = 0
        self._trial_start_click_count = 0

        # CSV file handle caching for reduced I/O overhead
        self._csv_file = None
        self._csv_filepath: Optional[Path] = None
        self._csv_header_written = False

    @property
    def device_type(self) -> DRTDeviceType:
        """Return the device type."""
        return DRTDeviceType.SDRT

    # =========================================================================
    # Command Methods
    # =========================================================================

    async def send_command(self, command: str, value: Optional[str] = None) -> bool:
        """
        Send a command to the sDRT device.

        Args:
            command: Command key from SDRT_COMMANDS
            value: Optional value for the command

        Returns:
            True if command was sent successfully
        """
        if command not in SDRT_COMMANDS:
            logger.error("Unknown sDRT command: %s", command)
            return False

        cmd_string = SDRT_COMMANDS[command]

        # Build command with optional value
        if value is not None:
            full_cmd = f"{cmd_string} {value}"
        else:
            full_cmd = cmd_string

        # Send with sDRT line ending
        return await self.transport.write_line(full_cmd, SDRT_LINE_ENDING)

    async def start_experiment(self) -> bool:
        """
        Start the experiment on the sDRT device.

        Resets click counter, opens CSV file, and sends the start command.

        Returns:
            True if experiment started successfully
        """
        self._click_count = 0
        self._device_click_count = 0
        self._trial_start_click_count = 0
        self._buffered_trial_data = None
        self._recording = True
        self._open_csv_file()
        return await self.send_command('start')

    async def stop_experiment(self) -> bool:
        """
        Stop the experiment on the sDRT device.

        Returns:
            True if experiment stopped successfully
        """
        self._recording = False
        self._close_csv_file()
        return await self.send_command('stop')

    def _open_csv_file(self) -> None:
        """Open CSV file for writing trial data (caches handle for session)."""
        if self._csv_file is not None:
            return  # Already open

        if not self.output_dir:
            return

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            port_clean = self.device_id.lstrip('/').replace('/', '_').lower()
            filename = f"DRT_{port_clean}.csv"
            self._csv_filepath = self.output_dir / filename

            # Check if we need to write header (file doesn't exist or is empty)
            self._csv_header_written = self._csv_filepath.exists() and self._csv_filepath.stat().st_size > 0

            self._csv_file = open(self._csv_filepath, 'a', buffering=1)  # Line buffered
            if not self._csv_header_written:
                self._csv_file.write(self._get_csv_header() + '\n')
                self._csv_header_written = True

            logger.debug("Opened CSV file: %s", self._csv_filepath)
        except Exception as e:
            logger.error("Failed to open CSV file: %s", e)
            self._csv_file = None

    def _close_csv_file(self) -> None:
        """Close the cached CSV file handle."""
        if self._csv_file is not None:
            try:
                self._csv_file.close()
                logger.debug("Closed CSV file: %s", self._csv_filepath)
            except Exception as e:
                logger.error("Error closing CSV file: %s", e)
            finally:
                self._csv_file = None
                self._csv_filepath = None

    async def set_stimulus(self, on: bool) -> bool:
        """
        Turn stimulus on or off.

        Args:
            on: True to turn on, False to turn off

        Returns:
            True if command was sent successfully
        """
        command = 'stim_on' if on else 'stim_off'
        return await self.send_command(command)

    async def get_config(self) -> Optional[Dict[str, Any]]:
        """
        Request and return device configuration.

        Returns:
            Configuration dict, or None if failed/timeout
        """
        # Create a future to wait for config response
        self._config_future = asyncio.get_running_loop().create_future()

        # Send config request
        if not await self.send_command('get_config'):
            self._config_future = None
            return None

        try:
            # Wait for config response with timeout
            config = await asyncio.wait_for(self._config_future, timeout=2.0)
            return config
        except asyncio.TimeoutError:
            logger.warning("Config request timed out for %s", self.device_id)
            return None
        finally:
            self._config_future = None

    async def set_iso_params(self) -> bool:
        """
        Set ISO standard parameters on the device.

        Returns:
            True if all parameters were set successfully
        """
        success = True
        for param, value in SDRT_ISO_PRESET.items():
            cmd = f'set_{param}'
            if cmd in SDRT_COMMANDS:
                if not await self.send_command(cmd, str(value)):
                    success = False
        return success

    async def set_lower_isi(self, value: int) -> bool:
        """Set lower inter-stimulus interval (ms)."""
        return await self.send_command('set_lowerISI', str(value))

    async def set_upper_isi(self, value: int) -> bool:
        """Set upper inter-stimulus interval (ms)."""
        return await self.send_command('set_upperISI', str(value))

    async def set_stim_duration(self, value: int) -> bool:
        """Set stimulus duration (ms)."""
        return await self.send_command('set_stimDur', str(value))

    async def set_intensity(self, value: int) -> bool:
        """Set stimulus intensity (0-255)."""
        return await self.send_command('set_intensity', str(value))

    # =========================================================================
    # Response Processing
    # =========================================================================

    def _process_response(self, line: str) -> None:
        """
        Process a response line from the sDRT device.

        Args:
            line: Raw response line
        """
        if not line or RESPONSE_DELIMITER not in line:
            return

        try:
            # Split on delimiter: "key>value"
            parts = line.split(RESPONSE_DELIMITER, 1)
            if len(parts) != 2:
                return

            key, value = parts[0], parts[1]

            # Route to appropriate handler
            response_type = SDRT_RESPONSES.get(key)
            if response_type is None:
                logger.debug("Unknown sDRT response: %s", key)
                return

            if response_type == 'click':
                self._handle_click(value)
            elif response_type == 'trial':
                self._handle_trial(value)
            elif response_type == 'end':
                self._handle_end()
            elif response_type == 'stimulus':
                self._handle_stimulus(value)
            elif response_type == 'config':
                self._handle_config(value)

        except Exception as e:
            logger.error("Error processing sDRT response '%s': %s", line, e)

    def _handle_click(self, value: str) -> None:
        """Handle click response - device sends cumulative count."""
        try:
            # Device sends cumulative click count since experiment start
            self._device_click_count = int(value)
            # Calculate per-trial clicks as delta from trial start
            self._click_count = self._device_click_count - self._trial_start_click_count
            logger.debug("Click: device=%d, trial_start=%d, per_trial=%d",
                        self._device_click_count, self._trial_start_click_count, self._click_count)
            self._create_background_task(self._dispatch_data_event('click', {
                'count': self._click_count
            }))
        except ValueError:
            logger.error("Invalid click value: %s", value)

    def _handle_trial(self, value: str) -> None:
        """
        Handle trial response.

        Format: timestamp,trial_number,reaction_time
        """
        try:
            parts = value.split(',')
            if len(parts) >= 3:
                timestamp = int(parts[0])
                trial_number = int(parts[1])
                reaction_time = int(parts[2])

                # Don't capture clicks here - capture at logging time when stimulus turns off
                # This ensures we get the click count AFTER all click messages have arrived
                self._buffered_trial_data = {
                    'timestamp': timestamp,
                    'trial_number': trial_number,
                    'reaction_time': reaction_time,
                }

                logger.debug("Trial data: %s", self._buffered_trial_data)
                self._create_background_task(self._dispatch_data_event('trial', {
                    'timestamp': timestamp,
                    'trial_number': trial_number,
                    'reaction_time': reaction_time,
                }))

        except (ValueError, IndexError) as e:
            logger.error("Error parsing trial data '%s': %s", value, e)

    def _handle_end(self) -> None:
        """Handle experiment end response."""
        # Log any buffered trial data
        if self._buffered_trial_data:
            self._log_trial_data(self._buffered_trial_data)
            self._buffered_trial_data = None

        # Dispatch end event
        self._create_background_task(self._dispatch_data_event('end', {}))

    def _handle_stimulus(self, value: str) -> None:
        """Handle stimulus state change."""
        try:
            state = int(value)
            self._stimulus_on = state == 1

            if self._stimulus_on:
                # Stimulus ON: start of new trial
                # Save baseline and reset per-trial count
                self._trial_start_click_count = self._device_click_count
                self._click_count = 0
                logger.debug("Trial start: baseline click count = %d", self._trial_start_click_count)
            else:
                # Stimulus OFF: log trial data if we have it
                # This captures clicks from stimulus ON to stimulus OFF
                if self._buffered_trial_data:
                    self._log_trial_data(self._buffered_trial_data)
                    self._buffered_trial_data = None

            logger.debug("Stimulus state: %s", "ON" if self._stimulus_on else "OFF")
            self._create_background_task(self._dispatch_data_event('stimulus', {
                'state': self._stimulus_on
            }))

        except ValueError:
            logger.error("Invalid stimulus value: %s", value)

    def _handle_config(self, value: str) -> None:
        """
        Handle config response.

        Format: key1:value1,key2:value2,...
        """
        try:
            config = {}
            pairs = value.split(',')
            for pair in pairs:
                if ':' in pair:
                    k, v = pair.split(':', 1)
                    config[k.strip()] = v.strip()

            logger.debug("Config received: %s", config)
            self._create_background_task(self._dispatch_data_event('config', config))

            if self._config_future and not self._config_future.done():
                self._config_future.set_result(config)

        except Exception as e:
            logger.error("Error parsing config '%s': %s", value, e)

    # =========================================================================
    # Data Logging
    # =========================================================================

    def _get_csv_header(self) -> str:
        """Return the CSV header for sDRT data."""
        return SDRT_CSV_HEADER

    def _log_trial_data(self, data: Dict[str, Any]) -> None:
        """
        Log trial data to CSV file.

        Uses cached file handle for reduced I/O overhead during recording.

        Args:
            data: Trial data dictionary with keys:
                - timestamp: Device timestamp (ms)
                - trial_number: Trial number
                - reaction_time: Reaction time (ms) or -1 for timeout
                - clicks: Number of clicks/responses
        """
        if not self.output_dir:
            logger.warning("No output directory set, skipping data log")
            return

        try:
            # Ensure file is open (may have been closed unexpectedly)
            if self._csv_file is None:
                self._open_csv_file()
            if self._csv_file is None:
                logger.warning("Could not open CSV file, skipping data log")
                return

            # Prepare data line
            port_clean = self.device_id.lstrip('/').replace('/', '_').lower()
            unix_time = int(datetime.now().timestamp())
            device_timestamp = data.get('timestamp', 0)
            trial_number = data.get('trial_number', 0)
            clicks = data.get('clicks', self._click_count)
            reaction_time = data.get('reaction_time', RT_TIMEOUT_VALUE)

            device_id = f"DRT_{port_clean}"
            label = self._trial_label if self._trial_label else "NA"

            # CSV line: Device ID, Label, Unix time, MSecs, Trial#, Responses, RT
            csv_line = f"{device_id},{label},{unix_time},{device_timestamp},{trial_number},{clicks},{reaction_time}\n"

            # Write to cached file handle (line-buffered, so flushes automatically)
            self._csv_file.write(csv_line)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Logged trial data to %s (clicks=%d)", self._csv_filepath, clicks)

            self._create_background_task(self._dispatch_data_event('trial_logged', {
                'filepath': str(self._csv_filepath),
                'trial_number': trial_number,
            }))

        except Exception as e:
            logger.error("Error logging trial data: %s", e)
