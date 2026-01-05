"""sDRT protocol handler for USB serial communication."""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from rpi_logger.core.logging_utils import get_module_logger
from .base_handler import BaseDRTHandler
from ..device_types import DRTDeviceType
from ..transports import USBTransport
from ..data_logger import DRTDataLogger
from ..protocols import (
    SDRT_COMMANDS,
    SDRT_RESPONSES,
    SDRT_LINE_ENDING,
    SDRT_ISO_PRESET,
    RESPONSE_DELIMITER,
)

logger = get_module_logger(__name__)


class SDRTHandler(BaseDRTHandler):
    """sDRT handler with experiment control, stimulus management, and logging."""

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

        # Data logger for CSV output
        self._data_logger = DRTDataLogger(
            output_dir=output_dir,
            device_id=device_id,
            device_type='sdrt',
            event_callback=self._dispatch_data_event,
        )

    @property
    def device_type(self) -> DRTDeviceType:
        """Return the device type."""
        return DRTDeviceType.SDRT

    def _update_data_logger_output_dir(self, output_dir: Path) -> None:
        """Update the data logger's output directory."""
        self._data_logger.output_dir = output_dir

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
        self._data_logger.set_trial_label(self._trial_label)
        self._data_logger.start_recording(self._active_trial_number)
        return await self.send_command('start')

    async def stop_experiment(self) -> bool:
        """
        Stop the experiment on the sDRT device.

        Returns:
            True if experiment stopped successfully
        """
        self._recording = False
        self._data_logger.stop_recording()
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
            trial_number = self._buffered_trial_data.get('trial_number', 0)
            if self._data_logger.log_trial(self._buffered_trial_data, self._click_count):
                self._create_background_task(
                    self._data_logger.dispatch_logged_event(trial_number)
                )
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
                    trial_number = self._buffered_trial_data.get('trial_number', 0)
                    if self._data_logger.log_trial(self._buffered_trial_data, self._click_count):
                        self._create_background_task(
                            self._data_logger.dispatch_logged_event(trial_number)
                        )
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
