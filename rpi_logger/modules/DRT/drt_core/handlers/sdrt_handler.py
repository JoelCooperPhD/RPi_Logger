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
            logger.error(f"Unknown sDRT command: {command}")
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

        Resets click counter and sends the start command.

        Returns:
            True if experiment started successfully
        """
        self._click_count = 0
        self._buffered_trial_data = None
        self._recording = True
        return await self.send_command('start')

    async def stop_experiment(self) -> bool:
        """
        Stop the experiment on the sDRT device.

        Returns:
            True if experiment stopped successfully
        """
        self._recording = False
        return await self.send_command('stop')

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
        self._config_future = asyncio.get_event_loop().create_future()

        # Send config request
        if not await self.send_command('get_config'):
            self._config_future = None
            return None

        try:
            # Wait for config response with timeout
            config = await asyncio.wait_for(self._config_future, timeout=2.0)
            return config
        except asyncio.TimeoutError:
            logger.warning(f"Config request timed out for {self.device_id}")
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
                logger.debug(f"Unknown sDRT response: {key}")
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
            logger.error(f"Error processing sDRT response '{line}': {e}")

    def _handle_click(self, value: str) -> None:
        """Handle click response."""
        try:
            click_value = int(value)
            self._click_count = click_value
            logger.debug(f"Click count: {self._click_count}")

            # Dispatch click event
            asyncio.create_task(self._dispatch_data_event('click', {
                'count': self._click_count
            }))
        except ValueError:
            logger.error(f"Invalid click value: {value}")

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

                self._buffered_trial_data = {
                    'timestamp': timestamp,
                    'trial_number': trial_number,
                    'reaction_time': reaction_time,
                    'clicks': self._click_count,
                }

                logger.debug(f"Trial data: {self._buffered_trial_data}")

                # Dispatch trial event
                asyncio.create_task(self._dispatch_data_event('trial', {
                    'timestamp': timestamp,
                    'trial_number': trial_number,
                    'reaction_time': reaction_time,
                }))

        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing trial data '{value}': {e}")

    def _handle_end(self) -> None:
        """Handle experiment end response."""
        # Log any buffered trial data
        if self._buffered_trial_data:
            self._log_trial_data(self._buffered_trial_data)
            self._buffered_trial_data = None

        # Dispatch end event
        asyncio.create_task(self._dispatch_data_event('end', {}))

    def _handle_stimulus(self, value: str) -> None:
        """Handle stimulus state change."""
        try:
            state = int(value)
            self._stimulus_on = state == 1

            # If stimulus turned off and we have buffered data, log it
            if not self._stimulus_on and self._buffered_trial_data:
                self._log_trial_data(self._buffered_trial_data)
                self._buffered_trial_data = None

            logger.debug(f"Stimulus state: {'ON' if self._stimulus_on else 'OFF'}")

            # Dispatch stimulus event
            asyncio.create_task(self._dispatch_data_event('stimulus', {
                'state': self._stimulus_on
            }))

        except ValueError:
            logger.error(f"Invalid stimulus value: {value}")

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

            logger.debug(f"Config received: {config}")

            # Dispatch config event
            asyncio.create_task(self._dispatch_data_event('config', config))

            # Complete config future if waiting
            if self._config_future and not self._config_future.done():
                self._config_future.set_result(config)

        except Exception as e:
            logger.error(f"Error parsing config '{value}': {e}")

    # =========================================================================
    # Data Logging
    # =========================================================================

    def _get_csv_header(self) -> str:
        """Return the CSV header for sDRT data."""
        return SDRT_CSV_HEADER

    def _log_trial_data(self, data: Dict[str, Any]) -> None:
        """
        Log trial data to CSV file.

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
            # Ensure output directory exists
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename
            port_clean = self.device_id.lstrip('/').replace('/', '_').lower()
            filename = f"sDRT_{port_clean}.csv"
            filepath = self.output_dir / filename

            # Prepare data line
            unix_time = int(datetime.now().timestamp())
            device_timestamp = data.get('timestamp', 0)
            trial_number = data.get('trial_number', 0)
            clicks = data.get('clicks', self._click_count)
            reaction_time = data.get('reaction_time', RT_TIMEOUT_VALUE)

            device_id = f"sDRT_{port_clean}"
            label = str(trial_number)  # Use trial number as label

            # CSV line: Device ID, Label, Unix time, MSecs, Trial#, Responses, RT
            csv_line = f"{device_id},{label},{unix_time},{device_timestamp},{trial_number},{clicks},{reaction_time}"

            # Write to file
            write_header = not filepath.exists()
            with open(filepath, 'a') as f:
                if write_header:
                    f.write(self._get_csv_header() + '\n')
                f.write(csv_line + '\n')

            logger.debug(f"Logged trial data to {filepath}")

            # Reset click count after logging
            self._click_count = 0

            # Dispatch logged event
            asyncio.create_task(self._dispatch_data_event('trial_logged', {
                'filepath': str(filepath),
                'trial_number': trial_number,
            }))

        except Exception as e:
            logger.error(f"Error logging trial data: {e}")
