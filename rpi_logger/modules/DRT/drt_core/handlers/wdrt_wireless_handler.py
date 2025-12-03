"""
wDRT Wireless Handler

Protocol handler for wDRT (Wireless Detection Response Task) devices connected via XBee.
Uses the same protocol as wDRT USB but communicates over XBee wireless.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import logging

from .base_handler import BaseDRTHandler
from ..device_types import DRTDeviceType
from ..transports import XBeeTransport
from ..protocols import (
    WDRT_COMMANDS,
    WDRT_RESPONSES,
    WDRT_LINE_ENDING,
    WDRT_CSV_HEADER,
    WDRT_CONFIG_PARAMS,
    RESPONSE_DELIMITER,
    RT_TIMEOUT_VALUE,
)
from ..utils.rtc import format_rtc_sync

logger = logging.getLogger(__name__)


class WDRTWirelessHandler(BaseDRTHandler):
    """
    Handler for wDRT devices connected via XBee wireless.

    Uses the same protocol as WDRTUSBHandler but communicates
    over an XBee 802.15.4 wireless connection.
    """

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: XBeeTransport
    ):
        """
        Initialize the wDRT wireless handler.

        Args:
            device_id: Unique identifier (XBee node ID, e.g., "wDRT_01")
            output_dir: Directory for CSV data files
            transport: XBee transport for device communication
        """
        super().__init__(device_id, output_dir, transport)

        # Config future for async config retrieval
        self._config_future: Optional[asyncio.Future] = None

        # wDRT-specific state
        self._stimulus_on = False
        self._battery_percent: Optional[int] = None
        self._device_utc: Optional[int] = None

        # RTC is synced by XBeeManager on discovery
        self._rtc_synced = True

    @property
    def device_type(self) -> DRTDeviceType:
        """Return the device type."""
        return DRTDeviceType.WDRT_WIRELESS

    @property
    def battery_percent(self) -> Optional[int]:
        """Return the last known battery percentage."""
        return self._battery_percent

    @property
    def node_id(self) -> str:
        """Return the XBee node ID."""
        return self.device_id

    # =========================================================================
    # Command Methods
    # =========================================================================

    async def send_command(self, command: str, value: Optional[str] = None) -> bool:
        """
        Send a command to the wDRT device over XBee.

        Args:
            command: Command key from WDRT_COMMANDS
            value: Optional value for the command

        Returns:
            True if command was sent successfully
        """
        if command not in WDRT_COMMANDS:
            logger.error(f"Unknown wDRT command: {command}")
            return False

        cmd_string = WDRT_COMMANDS[command]

        # Build command with optional value
        if value is not None:
            full_cmd = f"{cmd_string}{value}"
        else:
            full_cmd = cmd_string

        logger.debug(f"Sending command to {self.device_id}: '{full_cmd}'")
        # Send with wDRT line ending
        result = await self.transport.write_line(full_cmd, WDRT_LINE_ENDING)
        logger.debug(f"Command send result for {self.device_id}: {result}")
        return result

    async def start_experiment(self) -> bool:
        """
        Start the experiment on the wDRT device.

        Returns:
            True if experiment started successfully
        """
        logger.debug(f"Starting experiment on {self.device_id}")
        self._click_count = 0
        self._buffered_trial_data = None
        self._recording = True
        result = await self.send_command('start')
        logger.debug(f"Start experiment result for {self.device_id}: {result}")
        return result

    async def stop_experiment(self) -> bool:
        """
        Stop the experiment on the wDRT device.

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
        self._config_future = asyncio.get_event_loop().create_future()

        if not await self.send_command('get_config'):
            self._config_future = None
            return None

        try:
            config = await asyncio.wait_for(self._config_future, timeout=2.0)
            return config
        except asyncio.TimeoutError:
            logger.warning(f"Config request timed out for {self.device_id}")
            return None
        finally:
            self._config_future = None

    async def set_iso_params(self) -> bool:
        """Set ISO standard parameters on the device."""
        return await self.send_command('iso')

    async def get_battery(self) -> Optional[int]:
        """
        Request battery percentage from the device.

        Returns:
            Battery percentage, or None if failed
        """
        if await self.send_command('get_battery'):
            await asyncio.sleep(0.3)  # Slightly longer for wireless
            return self._battery_percent
        return None

    async def sync_rtc(self) -> bool:
        """
        Synchronize the device's real-time clock.

        Returns:
            True if sync command was sent successfully
        """
        rtc_string = format_rtc_sync()
        logger.info(f"Syncing RTC for {self.device_id}: {rtc_string}")
        return await self.send_command('set_rtc', rtc_string)

    async def set_config_param(self, param: str, value: int) -> bool:
        """
        Set a configuration parameter on the device.

        Args:
            param: Parameter name
            value: Parameter value

        Returns:
            True if command was sent successfully
        """
        device_param = param
        for dev_name, human_name in WDRT_CONFIG_PARAMS.items():
            if human_name == param:
                device_param = dev_name
                break

        return await self.send_command('set', f"{device_param},{value}")

    # =========================================================================
    # Response Processing
    # =========================================================================

    def _process_response(self, line: str) -> None:
        """
        Process a response line from the wDRT device.

        Args:
            line: Raw response line
        """
        if not line:
            return

        logger.debug(f"Processing response from {self.device_id}: '{line}'")

        if RESPONSE_DELIMITER not in line:
            logger.debug(f"Unrecognized wDRT response format: {line}")
            return

        try:
            parts = line.split(RESPONSE_DELIMITER, 1)
            if len(parts) != 2:
                return

            key, value = parts[0], parts[1]

            response_type = WDRT_RESPONSES.get(key)
            if response_type is None:
                logger.debug(f"Unknown wDRT response: {key}")
                return

            logger.debug(f"Handling {response_type} response: {value}")

            if response_type == 'click':
                self._handle_click(value)
            elif response_type == 'trial':
                self._handle_trial(value)
            elif response_type == 'reaction_time':
                self._handle_rt(value)
            elif response_type == 'stimulus':
                self._handle_stimulus(value)
            elif response_type == 'config':
                self._handle_config(value)
            elif response_type == 'battery':
                self._handle_battery(value)
            elif response_type == 'experiment':
                self._handle_experiment(value)
            elif response_type == 'data':
                self._handle_data(value)

        except Exception as e:
            logger.error(f"Error processing wDRT response '{line}': {e}")

    def _handle_click(self, value: str) -> None:
        """Handle click response."""
        try:
            self._click_count = int(value)
            asyncio.create_task(self._dispatch_data_event('click', {
                'count': self._click_count
            }))
        except ValueError:
            logger.error(f"Invalid click value: {value}")

    def _handle_trial(self, value: str) -> None:
        """Handle trial number response."""
        try:
            self._trial_number = int(value)
            asyncio.create_task(self._dispatch_data_event('trial', {
                'trial_number': self._trial_number
            }))
        except ValueError:
            logger.error(f"Invalid trial value: {value}")

    def _handle_rt(self, value: str) -> None:
        """Handle reaction time response."""
        try:
            reaction_time = int(value)
            asyncio.create_task(self._dispatch_data_event('reaction_time', {
                'reaction_time': reaction_time
            }))
        except ValueError:
            logger.error(f"Invalid RT value: {value}")

    def _handle_stimulus(self, value: str) -> None:
        """Handle stimulus state change."""
        try:
            state = int(value)
            self._stimulus_on = state == 1
            asyncio.create_task(self._dispatch_data_event('stimulus', {
                'state': self._stimulus_on
            }))
        except ValueError:
            logger.error(f"Invalid stimulus value: {value}")

    def _handle_config(self, value: str) -> None:
        """Handle config response."""
        try:
            config = {}
            if ',' in value and ':' in value:
                pairs = value.split(',')
                for pair in pairs:
                    if ':' in pair:
                        k, v = pair.split(':', 1)
                        human_name = WDRT_CONFIG_PARAMS.get(k.strip(), k.strip())
                        config[human_name] = v.strip()
            else:
                config['raw'] = value

            asyncio.create_task(self._dispatch_data_event('config', config))

            if self._config_future and not self._config_future.done():
                self._config_future.set_result(config)

        except Exception as e:
            logger.error(f"Error parsing config '{value}': {e}")

    def _handle_battery(self, value: str) -> None:
        """Handle battery percentage response."""
        try:
            self._battery_percent = int(value)
            asyncio.create_task(self._dispatch_data_event('battery', {
                'percent': self._battery_percent
            }))
        except ValueError:
            logger.error(f"Invalid battery value: {value}")

    def _handle_experiment(self, value: str) -> None:
        """Handle experiment state response."""
        try:
            state = int(value)
            self._recording = state == 1
            asyncio.create_task(self._dispatch_data_event('experiment', {
                'running': self._recording
            }))
        except ValueError:
            logger.error(f"Invalid experiment value: {value}")

    def _handle_data(self, value: str) -> None:
        """
        Handle data packet response.

        Format: block_ms,trial_n,clicks,rt,battery,device_utc
        """
        try:
            parts = value.split(',')
            if len(parts) >= 6:
                block_ms = int(parts[0])
                trial_n = int(parts[1])
                clicks = int(parts[2])
                rt = int(parts[3])
                battery = int(parts[4])
                device_utc = int(parts[5])

                self._battery_percent = battery
                self._device_utc = device_utc
                self._trial_number = trial_n

                trial_data = {
                    'timestamp': block_ms,
                    'trial_number': trial_n,
                    'clicks': clicks,
                    'reaction_time': rt,
                    'battery': battery,
                    'device_utc': device_utc,
                }

                self._log_trial_data(trial_data)

                asyncio.create_task(self._dispatch_data_event('data', trial_data))

        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing data packet '{value}': {e}")

    # =========================================================================
    # Data Logging
    # =========================================================================

    def _get_csv_header(self) -> str:
        """Return the CSV header for wDRT data."""
        return WDRT_CSV_HEADER

    def _log_trial_data(self, data: Dict[str, Any]) -> None:
        """
        Log trial data to CSV file.

        Args:
            data: Trial data dictionary
        """
        if not self.output_dir:
            logger.warning("No output directory set, skipping data log")
            return

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # Use node ID for filename (e.g., wDRT_01.csv)
            node_clean = self.device_id.replace('_', '').lower()
            filename = f"wDRT_{node_clean}.csv"
            filepath = self.output_dir / filename

            unix_time = int(datetime.now().timestamp())
            device_timestamp = data.get('timestamp', 0)
            trial_number = data.get('trial_number', 0)
            clicks = data.get('clicks', 0)
            reaction_time = data.get('reaction_time', RT_TIMEOUT_VALUE)
            battery = data.get('battery', 0)
            device_utc = data.get('device_utc', 0)

            # Use node ID as device ID
            device_id = self.device_id
            # Use trial_label if set, otherwise fall back to trial number
            label = self._trial_label if self._trial_label else str(trial_number)

            csv_line = (
                f"{device_id},{label},{unix_time},{device_timestamp},"
                f"{trial_number},{clicks},{reaction_time},{battery},{device_utc}"
            )

            write_header = not filepath.exists()
            with open(filepath, 'a') as f:
                if write_header:
                    f.write(self._get_csv_header() + '\n')
                f.write(csv_line + '\n')

            logger.debug(f"Logged trial data to {filepath}")

            asyncio.create_task(self._dispatch_data_event('trial_logged', {
                'filepath': str(filepath),
                'trial_number': trial_number,
            }))

        except Exception as e:
            logger.error(f"Error logging trial data: {e}")
