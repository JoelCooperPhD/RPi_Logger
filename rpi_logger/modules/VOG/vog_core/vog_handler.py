"""VOG device handler for serial communication with protocol abstraction."""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base import USBSerialDevice
from rpi_logger.modules.base.storage_utils import module_filename_prefix
from rpi_logger.core.commands import StatusMessage

from .protocols import BaseVOGProtocol, SVOGProtocol, WVOGProtocol, VOGDataPacket, VOGResponse
from .protocols.base_protocol import ResponseType


class VOGHandler:
    """Per-device handler for VOG serial communication.

    Uses protocol abstraction to support both sVOG (wired) and wVOG (wireless) devices.
    The protocol is automatically detected based on device VID/PID.
    """

    # Device identification
    SVOG_VID = 0x16C0
    SVOG_PID = 0x0483
    WVOG_VID = 0xf057
    WVOG_PID = 0x08AE

    def __init__(
        self,
        device: USBSerialDevice,
        port: str,
        output_dir: Path,
        system: Optional[Any] = None,
        protocol: Optional[BaseVOGProtocol] = None
    ):
        self.device = device
        self.port = port
        self.output_dir = output_dir
        self.system = system
        self._read_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._data_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None

        # Auto-detect protocol if not provided
        if protocol is None:
            self.protocol = self._detect_protocol()
        else:
            self.protocol = protocol

        # Device state
        self._config: Dict[str, Any] = {}
        self._trial_number = 0
        self._recording_start_time: Optional[float] = None
        self._battery_percent: int = 0

        self.logger = get_module_logger(f"VOGHandler[{self.protocol.device_type}]")

    def _detect_protocol(self) -> BaseVOGProtocol:
        """Detect protocol based on device VID/PID."""
        # Check device config for VID/PID (USBSerialDevice stores these in config)
        config = getattr(self.device, 'config', None)
        if config:
            vid = getattr(config, 'vid', None)
            pid = getattr(config, 'pid', None)
        else:
            vid = getattr(self.device, 'vid', None)
            pid = getattr(self.device, 'pid', None)

        if vid == self.WVOG_VID and pid == self.WVOG_PID:
            return WVOGProtocol()

        # Default to sVOG
        return SVOGProtocol()

    @property
    def device_type(self) -> str:
        """Return device type identifier."""
        return self.protocol.device_type

    @property
    def supports_dual_lens(self) -> bool:
        """Return True if device supports dual lens control."""
        return self.protocol.supports_dual_lens

    @property
    def supports_battery(self) -> bool:
        """Return True if device reports battery status."""
        return self.protocol.supports_battery

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
        self.logger.info("Started VOG handler (%s) for %s", self.device_type, self.port)

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
        """Send a command to the VOG device.

        Args:
            command: Command key (e.g., 'exp_start', 'get_config')
            value: Optional value for set commands

        Returns:
            True if command was sent successfully
        """
        if not self.protocol.has_command(command):
            self.logger.warning("Unknown %s command: %s", self.device_type, command)
            return False

        data = self.protocol.format_command(command, value)

        if not data:
            self.logger.warning("Failed to format command: %s", command)
            return False

        self.logger.info("Sending to %s: %r (len=%d)", self.port, data, len(data))
        success = await self.device.write(data)

        if success:
            self.logger.info("Command sent to %s: %s", self.port, command)
            # Small delay to let firmware process the command
            await asyncio.sleep(0.05)
        else:
            self.logger.error("Failed to send command to %s: %s", self.port, command)

        return success

    async def initialize_device(self) -> bool:
        """Initialize the VOG device."""
        self.logger.info("Initializing %s device on %s", self.device_type.upper(), self.port)
        return True

    async def close_device(self) -> bool:
        """Close the VOG device."""
        self.logger.info("Closing %s device on %s", self.device_type.upper(), self.port)
        return True

    async def start_experiment(self) -> bool:
        """Send experiment start command.

        For wVOG: sends exp>1 to initialize experiment.
        For sVOG: sends do_expStart.

        Note: This only initializes the experiment. To start cycling/trial,
        call start_trial() separately.
        """
        self._trial_number = 0
        self._recording_start_time = datetime.now().timestamp()
        self.logger.info("Starting experiment on %s", self.port)

        return await self.send_command('exp_start')

    async def stop_experiment(self) -> bool:
        """Send experiment stop command.

        For wVOG: sends exp>0 to close experiment.
        For sVOG: sends do_expStop.

        Note: This only stops the experiment. To stop the trial/cycling first,
        call stop_trial() separately before this.
        """
        self.logger.info("Stopping experiment on %s", self.port)

        self._recording_start_time = None
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

    async def peek_open(self, lens: str = 'x') -> bool:
        """Send peek/lens open command.

        Args:
            lens: 'a', 'b', or 'x' (both) - only used for wVOG
        """
        if self.supports_dual_lens:
            return await self.send_command(f'lens_open_{lens.lower()}')
        return await self.send_command('peek_open')

    async def peek_close(self, lens: str = 'x') -> bool:
        """Send peek/lens close command.

        Args:
            lens: 'a', 'b', or 'x' (both) - only used for wVOG
        """
        if self.supports_dual_lens:
            return await self.send_command(f'lens_close_{lens.lower()}')
        return await self.send_command('peek_close')

    async def get_device_config(self) -> Dict[str, Any]:
        """Request configuration from device.

        For sVOG: Sends individual get commands rapidly (no delay between commands,
        matching RS_Logger behavior).
        For wVOG: Sends single get_config command which returns all values.
        """
        self.logger.debug("Requesting configuration from %s", self.port)

        if self.device_type == 'wvog':
            # wVOG returns all config in one command
            await self.send_command('get_config')
        else:
            # sVOG: send individual get commands rapidly (no delay)
            # RS_Logger sends these without any delay between commands
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
                # No delay - RS_Logger sends commands in rapid succession

        return self._config

    async def set_config_value(self, param: str, value: str) -> bool:
        """Set a configuration value on the device.

        Args:
            param: Parameter name
            value: Value to set

        Returns:
            True if command was sent successfully
        """
        if self.device_type == 'wvog':
            # wVOG uses set>{key},{value} format
            return await self.send_command('set_config', f'{param},{value}')
        else:
            # sVOG uses separate commands for each parameter
            command = f'set_{param}'
            if not self.protocol.has_command(command):
                self.logger.warning("Unknown config parameter: %s", param)
                return False
            return await self.send_command(command, value)

    async def get_battery(self) -> int:
        """Request battery status (wVOG only)."""
        if not self.supports_battery:
            return -1
        await self.send_command('get_battery')
        return self._battery_percent

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
            parsed = self.protocol.parse_response(response)

            if parsed is None:
                self.logger.debug("Unrecognized response: %s", response)
                return

            data = {
                'keyword': parsed.keyword,
                'value': parsed.value,
                'raw': parsed.raw,
                'event': parsed.response_type.value,
            }
            data.update(parsed.data)

            # Process by response type
            if parsed.response_type == ResponseType.VERSION:
                self._config['deviceVer'] = parsed.value

            elif parsed.response_type == ResponseType.CONFIG:
                if self.device_type == 'wvog':
                    # wVOG returns all config at once
                    self._config.update(parsed.data.get('config', {}))
                else:
                    # sVOG returns one config value at a time
                    self._config[parsed.keyword] = parsed.value

            elif parsed.response_type == ResponseType.BATTERY:
                self._battery_percent = parsed.data.get('percent', 0)
                self._config['battery'] = self._battery_percent

            elif parsed.response_type == ResponseType.STIMULUS:
                data['state'] = parsed.data.get('state', 0)

            elif parsed.response_type == ResponseType.DATA:
                await self._process_data_response(parsed.value, data)

            # Dispatch event
            await self._dispatch_data_event(parsed.response_type.value, data)

            # Send status message if GUI commands enabled
            if self.system and getattr(self.system, 'enable_gui_commands', False):
                payload = {'port': self.port, 'device_type': self.device_type}
                payload.update(data)
                StatusMessage.send('vog_event', payload)

        except Exception as e:
            self.logger.error("Error processing response from %s: %s", self.port, e)

    async def _process_data_response(self, value: str, data: Dict[str, Any]):
        """Process a data response and log to CSV."""
        # Skip empty values (e.g., from 'end' marker)
        if not value or not value.strip():
            return

        port_clean = self.port.lstrip('/').replace('/', '_').replace('\\', '_')
        device_id = f"{self.device_type.upper()}_{port_clean}"

        packet = self.protocol.parse_data_response(value, device_id)

        if packet is None:
            self.logger.warning("Could not parse data response: %s", value)
            return

        # Update data dict with parsed values
        data['trial_number'] = packet.trial_number
        data['shutter_open'] = packet.shutter_open
        data['shutter_closed'] = packet.shutter_closed

        if self.device_type == 'wvog':
            data['shutter_total'] = packet.shutter_total
            data['lens'] = packet.lens
            data['battery_percent'] = packet.battery_percent
            data['device_unix_time'] = packet.device_unix_time

        # Log to CSV
        await self._log_trial_data(packet)

    async def _dispatch_data_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Dispatch data event to callback."""
        self.logger.debug("Dispatch event: type=%s data=%s", event_type, data)
        if not self._data_callback:
            return

        try:
            if asyncio.iscoroutinefunction(self._data_callback):
                await self._data_callback(self.port, event_type, data)
            else:
                self._data_callback(self.port, event_type, data)
        except Exception as exc:
            self.logger.error("Error in data callback for %s: %s", self.port, exc)

    def _determine_trial_number(self, packet: VOGDataPacket) -> int:
        """Determine trial number from system or packet data.

        Prioritizes system's active_trial_number to match other modules,
        falls back to packet trial number or internal counter.
        """
        candidate = None
        if self.system is not None:
            candidate = getattr(self.system, "active_trial_number", None)
            if not candidate and hasattr(self.system, "model"):
                model = getattr(self.system, "model")
                candidate = getattr(model, "trial_number", None)
        if not candidate:
            candidate = packet.trial_number or self._trial_number
        try:
            numeric = int(candidate)
        except (TypeError, ValueError):
            numeric = 0
        return numeric if numeric and numeric > 0 else 1

    async def _log_trial_data(self, packet: VOGDataPacket):
        """Log trial data to CSV file."""
        try:
            await asyncio.to_thread(self.output_dir.mkdir, parents=True, exist_ok=True)

            trial_number = self._determine_trial_number(packet)
            prefix = module_filename_prefix(self.output_dir, "VOG", trial_number, code="VOG")
            port_name = self.port.lstrip('/').replace('/', '_').replace('\\', '_').lower()
            data_file = self.output_dir / f"{prefix}_{port_name}.csv"

            file_exists = await asyncio.to_thread(data_file.exists)

            if not file_exists:
                header = self.protocol.csv_header

                def write_header():
                    with open(data_file, 'w', encoding='utf-8') as f:
                        f.write(header + '\n')

                await asyncio.to_thread(write_header)
                self.logger.info("Created VOG data file: %s", data_file.name)

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

            # Format CSV line based on device type
            if self.device_type == 'wvog' and hasattr(self.protocol, 'to_extended_csv_row'):
                line = self.protocol.to_extended_csv_row(packet, label, unix_time, ms_since_record)
            else:
                line = packet.to_csv_row(label, unix_time, ms_since_record)

            def append_line():
                with open(data_file, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')

            await asyncio.to_thread(append_line)
            self.logger.debug(
                "Logged trial: T=%s, Open=%s, Closed=%s",
                trial_number, packet.shutter_open, packet.shutter_closed
            )

            # Dispatch logged event
            log_payload = {
                'device_id': packet.device_id,
                'device_type': self.device_type,
                'label': label,
                'unix_time': unix_time,
                'ms_since_record': ms_since_record,
                'trial_number': trial_number,
                'shutter_open': packet.shutter_open,
                'shutter_closed': packet.shutter_closed,
                'file_path': str(data_file),
            }

            if self.device_type == 'wvog':
                log_payload['shutter_total'] = packet.shutter_total
                log_payload['lens'] = packet.lens
                log_payload['battery_percent'] = packet.battery_percent

            await self._dispatch_data_event('trial_logged', log_payload)

        except Exception as e:
            self.logger.error("Error logging trial data: %s", e, exc_info=True)
