"""
wDRT Base Handler

Shared implementation for wDRT (Wireless Detection Response Task) devices.
Both USB and Wireless variants share the same protocol, differing only in
transport layer and minor configuration.
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from rpi_logger.core.logging_utils import get_module_logger
from .base_handler import BaseDRTHandler
from ..data_logger import DRTDataLogger
from ..protocols import (
    WDRT_COMMANDS,
    WDRT_RESPONSES,
    WDRT_LINE_ENDING,
    WDRT_CONFIG_PARAMS,
    RESPONSE_DELIMITER,
)
from ..utils.rtc import format_rtc_sync

logger = get_module_logger(__name__)


class WDRTBaseHandler(BaseDRTHandler):
    """
    Base handler for wDRT devices.

    Implements the wDRT protocol for experiment control, stimulus management,
    battery monitoring, RTC sync, and data logging. Subclasses specify the
    transport type and device type enum.
    """

    # Battery polling interval in seconds (when not recording)
    BATTERY_POLL_INTERVAL = 10.0

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: Any
    ):
        super().__init__(device_id, output_dir, transport)

        self._config_future: Optional[asyncio.Future] = None
        self._stimulus_on = False
        self._battery_percent: Optional[int] = None
        self._device_utc: Optional[int] = None
        self._rtc_synced = False
        self._battery_poll_task: Optional[asyncio.Task] = None

        # Data logger for CSV output
        self._data_logger = DRTDataLogger(
            output_dir=output_dir,
            device_id=device_id,
            device_type='wdrt',
            event_callback=self._dispatch_data_event,
        )

    @property
    def battery_percent(self) -> Optional[int]:
        """Return the last known battery percentage."""
        return self._battery_percent

    def _update_data_logger_output_dir(self, output_dir: Path) -> None:
        """Update the data logger's output directory."""
        self._data_logger.output_dir = output_dir

    # =========================================================================
    # Battery Polling
    # =========================================================================

    def _start_battery_polling(self) -> None:
        """Start background battery polling task."""
        if self._battery_poll_task is not None and not self._battery_poll_task.done():
            return  # Already running

        self._battery_poll_task = asyncio.create_task(
            self._battery_poll_loop(),
            name=f"battery_poll_{self.device_id}"
        )
        logger.debug("Started battery polling for %s", self.device_id)

    def _stop_battery_polling(self) -> None:
        """Stop background battery polling task."""
        if self._battery_poll_task is not None:
            self._battery_poll_task.cancel()
            self._battery_poll_task = None
            logger.debug("Stopped battery polling for %s", self.device_id)

    async def _battery_poll_loop(self) -> None:
        """Background loop that polls battery every BATTERY_POLL_INTERVAL seconds."""
        try:
            while self._running and not self._recording:
                await self.get_battery()
                await asyncio.sleep(self.BATTERY_POLL_INTERVAL)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error in battery poll loop for %s: %s", self.device_id, e)

    async def stop(self) -> None:
        """Stop the handler and clean up battery polling."""
        self._stop_battery_polling()
        await super().stop()

    async def send_command(self, command: str, value: Optional[str] = None) -> bool:
        if command not in WDRT_COMMANDS:
            logger.error("Unknown wDRT command: %s", command)
            return False

        cmd_string = WDRT_COMMANDS[command]
        full_cmd = f"{cmd_string}{value}" if value is not None else cmd_string

        return await self.transport.write_line(full_cmd, WDRT_LINE_ENDING)

    async def start_experiment(self) -> bool:
        # Stop battery polling during recording
        self._stop_battery_polling()

        self._click_count = 0
        self._buffered_trial_data = None
        self._recording = True
        self._data_logger.set_trial_label(self._trial_label)
        self._data_logger.start_recording(self._active_trial_number)
        return await self.send_command('start')

    async def stop_experiment(self) -> bool:
        self._recording = False
        self._data_logger.stop_recording()
        result = await self.send_command('stop')

        # Resume battery polling after recording stops
        if self._running:
            self._start_battery_polling()

        return result

    async def set_stimulus(self, on: bool) -> bool:
        command = 'stim_on' if on else 'stim_off'
        return await self.send_command(command)

    async def get_config(self) -> Optional[Dict[str, Any]]:
        self._config_future = asyncio.get_running_loop().create_future()

        if not await self.send_command('get_config'):
            self._config_future = None
            return None

        try:
            config = await asyncio.wait_for(self._config_future, timeout=2.0)
            return config
        except asyncio.TimeoutError:
            logger.warning("Config request timed out for %s", self.device_id)
            return None
        finally:
            self._config_future = None

    async def set_iso_params(self) -> bool:
        """Set ISO standard parameters on the device."""
        return await self.send_command('iso')

    async def get_battery(self) -> Optional[int]:
        """Request battery percentage from the device."""
        if await self.send_command('get_battery'):
            await asyncio.sleep(0.2)
            return self._battery_percent
        return None

    async def sync_rtc(self) -> bool:
        """Synchronize the device's real-time clock with host time."""
        rtc_string = format_rtc_sync()
        logger.info("Syncing RTC for %s: %s", self.device_id, rtc_string)
        return await self.send_command('set_rtc', rtc_string)

    async def set_config_param(self, param: str, value: int) -> bool:
        """Set a configuration parameter on the device."""
        device_param = param
        for dev_name, human_name in WDRT_CONFIG_PARAMS.items():
            if human_name == param:
                device_param = dev_name
                break

        return await self.send_command('set', f"{device_param},{value}")

    def _process_response(self, line: str) -> None:
        if not line:
            return

        if RESPONSE_DELIMITER not in line:
            logger.debug("Unrecognized wDRT response format: %s", line)
            return

        try:
            parts = line.split(RESPONSE_DELIMITER, 1)
            if len(parts) != 2:
                return

            key, value = parts[0], parts[1]

            response_type = WDRT_RESPONSES.get(key)
            if response_type is None:
                logger.debug("Unknown wDRT response: %s", key)
                return

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
            logger.error("Error processing wDRT response '%s': %s", line, e)

    def _handle_click(self, value: str) -> None:
        try:
            self._click_count = int(value)
            self._create_background_task(self._dispatch_data_event('click', {
                'count': self._click_count
            }))
        except ValueError:
            logger.error("Invalid click value: %s", value)

    def _handle_trial(self, value: str) -> None:
        try:
            self._trial_number = int(value)
            self._create_background_task(self._dispatch_data_event('trial', {
                'trial_number': self._trial_number
            }))
        except ValueError:
            logger.error("Invalid trial value: %s", value)

    def _handle_rt(self, value: str) -> None:
        try:
            reaction_time = int(value)
            self._create_background_task(self._dispatch_data_event('reaction_time', {
                'reaction_time': reaction_time
            }))
        except ValueError:
            logger.error("Invalid RT value: %s", value)

    def _handle_stimulus(self, value: str) -> None:
        try:
            state = int(value)
            self._stimulus_on = state == 1
            self._create_background_task(self._dispatch_data_event('stimulus', {
                'state': self._stimulus_on
            }))
        except ValueError:
            logger.error("Invalid stimulus value: %s", value)

    def _handle_config(self, value: str) -> None:
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

            self._create_background_task(self._dispatch_data_event('config', config))

            if self._config_future and not self._config_future.done():
                self._config_future.set_result(config)

        except Exception as e:
            logger.error("Error parsing config '%s': %s", value, e)

    def _handle_battery(self, value: str) -> None:
        try:
            self._battery_percent = int(value)
            self._create_background_task(self._dispatch_data_event('battery', {
                'percent': self._battery_percent
            }))
        except ValueError:
            logger.error("Invalid battery value: %s", value)

    def _handle_experiment(self, value: str) -> None:
        try:
            state = int(value)
            self._recording = state == 1
            self._create_background_task(self._dispatch_data_event('experiment', {
                'running': self._recording
            }))
        except ValueError:
            logger.error("Invalid experiment value: %s", value)

    def _handle_data(self, value: str) -> None:
        """Handle data packet: block_ms,trial_n,clicks,rt,battery,device_utc"""
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

                if self._data_logger.log_trial(trial_data):
                    self._create_background_task(
                        self._data_logger.dispatch_logged_event(trial_n)
                    )
                self._create_background_task(self._dispatch_data_event('data', trial_data))

        except (ValueError, IndexError) as e:
            logger.error("Error parsing data packet '%s': %s", value, e)
