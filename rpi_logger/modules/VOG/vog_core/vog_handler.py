"""VOG device handler for serial communication."""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base import USBSerialDevice
from rpi_logger.modules.base.storage_utils import module_filename_prefix
from rpi_logger.core.commands import StatusMessage

from .constants import SVOG_COMMANDS, SVOG_RESPONSE_KEYWORDS, SVOG_RESPONSE_TYPES, CSV_HEADER


class VOGHandler:
    """Per-device handler for sVOG serial communication."""

    def __init__(
        self,
        device: USBSerialDevice,
        port: str,
        output_dir: Path,
        system: Optional[Any] = None
    ):
        self.device = device
        self.port = port
        self.output_dir = output_dir
        self.system = system
        self._read_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._data_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None

        # Device state
        self._config: Dict[str, Any] = {}
        self._trial_number = 0
        self._recording_start_time: Optional[float] = None

        self.logger = get_module_logger("VOGHandler")

    def set_data_callback(self, callback: Callable[[str, str, Dict[str, Any]], None]):
        """Set callback for data events."""
        self._data_callback = callback

    async def start(self):
        """Start the async read loop."""
        if self._running:
            return

        self._running = True
        loop = asyncio.get_running_loop()
        self._loop = loop
        self._read_task = loop.create_task(self._read_loop())
        self.logger.info("Started VOG handler for %s", self.port)

    async def stop(self):
        """Stop the async read loop."""
        if not self._running and not self._read_task:
            return

        self._running = False

        task = self._read_task
        self._read_task = None

        if task:
            origin_loop = self._loop
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None

            if origin_loop and origin_loop is not current_loop:
                if origin_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self._cancel_read_task(task), origin_loop
                    )
                    try:
                        await asyncio.wrap_future(future)
                    except RuntimeError as exc:
                        self.logger.warning(
                            "Failed to await read loop task for %s: %s",
                            self.port, exc
                        )
                else:
                    task.cancel()
            else:
                await self._cancel_read_task(task)

        self._loop = None
        self.logger.info("Stopped VOG handler for %s", self.port)

    async def _cancel_read_task(self, task: asyncio.Task):
        """Cancel the read task gracefully."""
        try:
            task.cancel()
            await task
        except asyncio.CancelledError:
            pass

    async def send_command(self, command: str, value: Optional[str] = None) -> bool:
        """Send a command to the sVOG device.

        Args:
            command: Command key from SVOG_COMMANDS
            value: Optional value for set commands

        Returns:
            True if command was sent successfully
        """
        if command not in SVOG_COMMANDS:
            self.logger.warning("Unknown VOG command: %s", command)
            return False

        cmd_string = SVOG_COMMANDS[command]

        # Substitute value if needed
        if value is not None and '{val}' in cmd_string:
            cmd_string = cmd_string.format(val=value)

        message = f"{cmd_string}\n"
        data = message.encode('utf-8')

        self.logger.debug("Sending to %s: %s", self.port, cmd_string)
        success = await self.device.write(data)

        if success:
            self.logger.debug("Command sent to %s: %s", self.port, command)
        else:
            self.logger.error("Failed to send command to %s: %s", self.port, command)

        return success

    async def initialize_device(self) -> bool:
        """Initialize the sVOG device."""
        self.logger.info("Initializing sVOG device on %s", self.port)
        return True

    async def close_device(self) -> bool:
        """Close the sVOG device."""
        self.logger.info("Closing sVOG device on %s", self.port)
        return True

    async def start_experiment(self) -> bool:
        """Send experiment start command."""
        self._trial_number = 0
        self._recording_start_time = datetime.now().timestamp()
        self.logger.info("Starting experiment on %s", self.port)
        return await self.send_command('exp_start')

    async def stop_experiment(self) -> bool:
        """Send experiment stop command."""
        self._recording_start_time = None
        self.logger.info("Stopping experiment on %s", self.port)
        return await self.send_command('exp_stop')

    async def start_trial(self) -> bool:
        """Send trial start command."""
        self._trial_number += 1
        self.logger.info("Starting trial %d on %s", self._trial_number, self.port)
        return await self.send_command('trial_start')

    async def stop_trial(self) -> bool:
        """Send trial stop command."""
        self.logger.info("Stopping trial on %s", self.port)
        return await self.send_command('trial_stop')

    async def peek_open(self) -> bool:
        """Send peek open command."""
        return await self.send_command('peek_open')

    async def peek_close(self) -> bool:
        """Send peek close command."""
        return await self.send_command('peek_close')

    async def get_device_config(self) -> Dict[str, Any]:
        """Request all configuration values from device."""
        self.logger.debug("Requesting configuration from %s", self.port)

        commands = [
            'get_device_ver',
            'get_config_name',
            'get_max_open',
            'get_max_close',
            'get_debounce',
            'get_click_mode',
            'get_button_control',
        ]

        for cmd in commands:
            await self.send_command(cmd)
            await asyncio.sleep(0.05)  # Small delay between commands

        return self._config

    async def set_config_value(self, param: str, value: str) -> bool:
        """Set a configuration value on the device.

        Args:
            param: Parameter name (e.g., 'config_name', 'max_open')
            value: Value to set

        Returns:
            True if command was sent successfully
        """
        command = f'set_{param}'
        if command not in SVOG_COMMANDS:
            self.logger.warning("Unknown config parameter: %s", param)
            return False

        return await self.send_command(command, value)

    async def _read_loop(self):
        """Main async read loop for incoming data."""
        try:
            while self._running and self.device.is_connected:
                line = await self.device.read_line()

                if line:
                    await self._process_response(line)

                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error("Error in read loop for %s: %s", self.port, e)

    async def _process_response(self, response: str):
        """Process a response line from the device."""
        self.logger.debug("Response from %s: %s", self.port, repr(response))

        try:
            # sVOG responses are in format: keyword|value
            if '|' not in response:
                self.logger.debug("Non-standard response (no pipe): %s", response)
                return

            parts = response.split('|', 1)
            keyword = parts[0]
            value = parts[1] if len(parts) > 1 else ''

            # Find matching response keyword
            response_type = None
            matched_keyword = None

            for kw in SVOG_RESPONSE_KEYWORDS:
                if kw in keyword:
                    matched_keyword = kw
                    response_type = SVOG_RESPONSE_TYPES.get(kw)
                    break

            if not response_type:
                self.logger.debug("Unrecognized response keyword: %s", keyword)
                return

            data = {
                'keyword': matched_keyword,
                'value': value,
                'raw': response,
            }

            if response_type == 'version':
                self._config['deviceVer'] = value
                data['event'] = 'version'

            elif response_type == 'config':
                self._config[matched_keyword] = value
                data['event'] = 'config'

            elif response_type == 'stimulus':
                data['event'] = 'stimulus'
                # Parse stimulus state (typically 0 or 1)
                try:
                    data['state'] = int(value)
                except ValueError:
                    data['state'] = value

            elif response_type == 'data':
                data['event'] = 'data'
                await self._process_data_response(value, data)

            # Dispatch event
            await self._dispatch_data_event(response_type, data)

            # Send status message if GUI commands enabled
            if self.system and getattr(self.system, 'enable_gui_commands', False):
                payload = {'port': self.port}
                payload.update(data)
                StatusMessage.send('vog_event', payload)

        except Exception as e:
            self.logger.error("Error processing response from %s: %s", self.port, e)

    async def _process_data_response(self, value: str, data: Dict[str, Any]):
        """Process a data response and log to CSV.

        Data format from device: trial_number,shutter_open,shutter_closed
        """
        try:
            parts = value.split(',')
            if len(parts) >= 3:
                data['trial_number'] = int(parts[0]) if parts[0] else self._trial_number
                data['shutter_open'] = int(parts[1]) if parts[1] else 0
                data['shutter_closed'] = int(parts[2]) if parts[2] else 0

                # Log to CSV
                await self._log_trial_data(data)

        except (ValueError, IndexError) as e:
            self.logger.warning("Could not parse data response: %s - %s", value, e)

    async def _dispatch_data_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Dispatch data event to callback."""
        if not self._data_callback:
            return

        try:
            if asyncio.iscoroutinefunction(self._data_callback):
                await self._data_callback(self.port, event_type, data)
            else:
                self._data_callback(self.port, event_type, data)
        except Exception as exc:
            self.logger.error("Error in data callback for %s: %s", self.port, exc)

    async def _log_trial_data(self, data: Dict[str, Any]):
        """Log trial data to CSV file."""
        try:
            await asyncio.to_thread(self.output_dir.mkdir, parents=True, exist_ok=True)

            trial_number = data.get('trial_number', self._trial_number or 1)
            prefix = module_filename_prefix(self.output_dir, "VOG", trial_number, code="VOG")
            port_name = self.port.lstrip('/').replace('/', '_').replace('\\', '_').lower()
            data_file = self.output_dir / f"{prefix}_{port_name}.csv"

            file_exists = await asyncio.to_thread(data_file.exists)

            if not file_exists:
                def write_header():
                    with open(data_file, 'w', encoding='utf-8') as f:
                        f.write(CSV_HEADER + '\n')

                await asyncio.to_thread(write_header)
                self.logger.info("Created VOG data file: %s", data_file.name)

            # Build CSV line
            port_clean = self.port.lstrip('/').replace('/', '_').replace('\\', '_')
            device_id = f"sVOG_{port_clean}"

            # Get label from system or use trial number
            if self.system and hasattr(self.system, 'trial_label') and self.system.trial_label:
                label = self.system.trial_label
            else:
                label = str(trial_number)

            unix_time = int(datetime.now().timestamp())

            # Calculate milliseconds since recording start
            if self._recording_start_time:
                ms_since_record = int((datetime.now().timestamp() - self._recording_start_time) * 1000)
            else:
                ms_since_record = 0

            shutter_open = data.get('shutter_open', '')
            shutter_closed = data.get('shutter_closed', '')

            line = f"{device_id}, {label}, {unix_time}, {ms_since_record}, {trial_number}, {shutter_open}, {shutter_closed}\n"

            def append_line():
                with open(data_file, 'a', encoding='utf-8') as f:
                    f.write(line)

            await asyncio.to_thread(append_line)
            self.logger.debug("Logged trial: T=%s, Open=%s, Closed=%s", trial_number, shutter_open, shutter_closed)

            # Dispatch logged event
            log_payload = {
                'device_id': device_id,
                'label': label,
                'unix_time': unix_time,
                'ms_since_record': ms_since_record,
                'trial_number': trial_number,
                'shutter_open': shutter_open,
                'shutter_closed': shutter_closed,
                'file_path': str(data_file),
            }
            await self._dispatch_data_event('trial_logged', log_payload)

        except Exception as e:
            self.logger.error("Error logging trial data: %s", e, exc_info=True)
