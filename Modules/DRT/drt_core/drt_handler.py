import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from Modules.base import USBSerialDevice
from .constants import DRT_COMMANDS, DRT_RESPONSE_TYPES, ISO_PRESET_CONFIG

logger = logging.getLogger(__name__)


class DRTHandler:
    def __init__(self, device: USBSerialDevice, port: str, output_dir: Path, system: Optional[Any] = None):
        self.device = device
        self.port = port
        self.output_dir = output_dir
        self.system = system
        self._read_task: Optional[asyncio.Task] = None
        self._running = False
        self._data_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
        self._config_future: Optional[asyncio.Future] = None
        self._click_count = 0
        self._buffered_trial_data: Optional[Dict[str, Any]] = None

    def set_data_callback(self, callback: Callable[[str, str, Dict[str, Any]], None]):
        self._data_callback = callback

    async def start(self):
        if self._running:
            return

        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())
        logger.info(f"Started DRT handler for {self.port}")

    async def stop(self):
        self._running = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        logger.info(f"Stopped DRT handler for {self.port}")

    async def send_command(self, command: str, value: Optional[str] = None) -> bool:
        if command not in DRT_COMMANDS:
            logger.warning(f"Unknown command: {command}")
            return False

        cmd_string = DRT_COMMANDS[command]

        if value:
            message = f"{cmd_string} {value}\n\r"
        else:
            message = f"{cmd_string}\n\r"

        data = message.encode('utf-8')
        success = await self.device.write(data)

        if success:
            logger.debug(f"Sent command to {self.port}: {message.strip()}")

        return success

    async def initialize_device(self) -> bool:
        logger.info(f"Initializing sDRT device on {self.port}")
        return True

    async def close_device(self) -> bool:
        logger.info(f"Closing sDRT device on {self.port}")
        return True

    async def start_experiment(self) -> bool:
        self._click_count = 0
        self._buffered_trial_data = None
        logger.info(f"Starting experiment on {self.port}, reset click counter and buffer")
        return await self.send_command('exp_start')

    async def stop_experiment(self) -> bool:
        return await self.send_command('exp_stop')

    def reset_data_file(self) -> None:
        logger.debug(f"reset_data_file called for {self.port} (no-op - filename calculated dynamically)")

    async def set_stimulus(self, enabled: bool) -> bool:
        command = 'stim_on' if enabled else 'stim_off'
        return await self.send_command(command)

    async def set_lower_isi(self, value: int) -> bool:
        return await self.send_command('set_lowerISI', str(value))

    async def set_upper_isi(self, value: int) -> bool:
        return await self.send_command('set_upperISI', str(value))

    async def set_stimulus_duration(self, value: int) -> bool:
        return await self.send_command('set_stimDur', str(value))

    async def set_intensity(self, value: int) -> bool:
        return await self.send_command('set_intensity', str(value))

    async def get_device_config(self) -> Optional[Dict[str, Any]]:
        logger.debug(f"Requesting configuration from {self.port}")

        self._config_future = asyncio.get_event_loop().create_future()

        success = await self.send_command('get_config')
        if not success:
            return None

        try:
            config_data = await asyncio.wait_for(self._config_future, timeout=2.0)
            return config_data
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for config response from {self.port}")
            return None
        finally:
            self._config_future = None

    async def set_iso_standard(self) -> bool:
        return await self.set_iso_params()

    async def set_iso_params(self) -> bool:
        logger.info(f"Setting ISO preset parameters on {self.port}")
        await self.send_command('set_lowerISI', str(ISO_PRESET_CONFIG['lowerISI']))
        await asyncio.sleep(0.05)
        await self.send_command('set_upperISI', str(ISO_PRESET_CONFIG['upperISI']))
        await asyncio.sleep(0.05)
        await self.send_command('set_stimDur', str(ISO_PRESET_CONFIG['stimDur']))
        await asyncio.sleep(0.05)
        await self.send_command('set_intensity', str(ISO_PRESET_CONFIG['intensity']))
        return True

    async def _read_loop(self):
        try:
            while self._running and self.device.is_connected:
                line = await self.device.read_line()

                if line:
                    await self._process_response(line)

                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in read loop for {self.port}: {e}")

    async def _process_response(self, response: str):
        logger.info(f"RAW MESSAGE from {self.port}: {repr(response)}")

        try:
            parts = response.split('>')
            logger.info(f"SPLIT PARTS: {parts}")

            if not parts:
                return

            response_key = parts[0].lower()
            response_type = None
            data = {}

            for key, rtype in DRT_RESPONSE_TYPES.items():
                if key in response_key:
                    response_type = rtype
                    break

            logger.info(f"MATCHED TYPE: {response_type} (key: {response_key})")

            if response_type == 'click':
                data = self._parse_click(parts)
                logger.info(f"PARSED CLICK: {data}")
            elif response_type == 'trial':
                data = self._parse_trial(parts)
                logger.info(f"PARSED TRIAL: {data}")
                self._buffered_trial_data = data
                logger.info(f"Buffered trial data - will write on next stimulus. Current clicks: {self._click_count}")
            elif response_type == 'experiment_end':
                data = {'event': 'experiment_end', 'raw': response}
                if self._buffered_trial_data:
                    logger.info(f"Experiment ended - writing buffered trial data with {self._click_count} clicks")
                    await self._log_trial_data(self._buffered_trial_data)
                    self._buffered_trial_data = None
            elif response_type == 'stimulus':
                data = self._parse_stimulus(parts)
                if self._buffered_trial_data:
                    logger.info(f"Stimulus detected - writing buffered trial data with {self._click_count} clicks")
                    await self._log_trial_data(self._buffered_trial_data)
                    self._buffered_trial_data = None
            elif response_type == 'config':
                data = self._parse_config(parts)
                if self._config_future and not self._config_future.done():
                    self._config_future.set_result(data)
            else:
                data = {'raw': response}

            if self._data_callback:
                try:
                    if asyncio.iscoroutinefunction(self._data_callback):
                        await self._data_callback(self.port, response_type or 'unknown', data)
                    else:
                        self._data_callback(self.port, response_type or 'unknown', data)
                except Exception as e:
                    logger.error(f"Error in data callback: {e}")

        except Exception as e:
            logger.error(f"Error processing response from {self.port}: {e}")

    def _parse_click(self, parts: list) -> Dict[str, Any]:
        value = parts[1] if len(parts) > 1 else ''
        self._click_count += 1
        logger.debug(f"Click detected on {self.port}, total clicks: {self._click_count}")
        return {
            'event': 'click',
            'value': value,
            'raw': '>'.join(parts)
        }

    def _parse_trial(self, parts: list) -> Dict[str, Any]:
        data = {
            'event': 'trial',
            'raw': '>'.join(parts)
        }

        if len(parts) > 1 and parts[1]:
            try:
                values = parts[1].split(',')
                if len(values) >= 3:
                    data['timestamp'] = int(values[0]) if values[0] else None
                    data['trial_number'] = int(values[1]) if values[1] else None
                    data['reaction_time'] = float(values[2]) if values[2] else None
                logger.info(f"Parsed trial: Timestamp={data.get('timestamp')}, Trial#={data.get('trial_number')}, RT={data.get('reaction_time')}")
            except (ValueError, IndexError) as e:
                logger.warning(f"Could not parse trial data: {e}")

        return data

    def _parse_stimulus(self, parts: list) -> Dict[str, Any]:
        value = parts[1] if len(parts) > 1 else ''
        return {
            'event': 'stimulus',
            'value': value,
            'raw': '>'.join(parts)
        }

    def _parse_config(self, parts: list) -> Dict[str, Any]:
        config_data = {
            'event': 'config',
            'raw': '>'.join(parts)
        }

        if len(parts) > 1:
            config_str = parts[1]
            pairs = config_str.split(',')

            for pair in pairs:
                if ':' in pair:
                    key, value = pair.split(':', 1)
                    key = key.strip()
                    value = value.strip()

                    try:
                        if key in ['lowerISI', 'upperISI', 'stimDur', 'intensity']:
                            config_data[key] = int(value)
                        else:
                            config_data[key] = value
                    except ValueError:
                        logger.warning(f"Could not parse config value for {key}: {value}")
                        config_data[key] = value

        return config_data

    async def _log_trial_data(self, data: Dict[str, Any]):
        try:
            dir_name = self.output_dir.name
            if "_" in dir_name:
                session_timestamp = dir_name.split("_", 1)[1]
            else:
                session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            port_name = self.port.lstrip('/').replace('/', '_').replace('\\', '_')
            filename = f"DRT_{port_name}_{session_timestamp}.csv"
            data_file = self.output_dir / filename

            logger.debug(f"DRT data file path: {data_file}")

            await asyncio.to_thread(self.output_dir.mkdir, parents=True, exist_ok=True)

            file_exists = await asyncio.to_thread(data_file.exists)

            if not file_exists:
                def write_header():
                    with open(data_file, 'w') as f:
                        f.write("Device ID, Label, Unix time in UTC, Milliseconds Since Record, Trial Number, Responses, Reaction Time\n")

                await asyncio.to_thread(write_header)
                logger.info(f"✓ Created DRT data file: {data_file}")
            else:
                logger.debug(f"Appending to existing DRT file: {data_file.name}")

            port_clean = self.port.lstrip('/').replace('/', '_').replace('\\', '_')
            device_id = f"sDRT_{port_clean}"
            trial_number = data.get('trial_number', '')

            if self.system and hasattr(self.system, 'trial_label') and self.system.trial_label:
                label = self.system.trial_label
            else:
                label = str(trial_number)

            unix_time = int(datetime.now().timestamp())
            device_timestamp = data.get('timestamp', '')
            rt_raw = data.get('reaction_time', '')

            rt = int(rt_raw) if rt_raw != '' else ''

            clicks = self._click_count
            if rt == -1 or rt == '-1':
                clicks = 0

            line = f"{device_id}, {label}, {unix_time}, {device_timestamp}, {trial_number}, {clicks}, {rt}\n"

            def append_line():
                with open(data_file, 'a') as f:
                    f.write(line)

            await asyncio.to_thread(append_line)
            logger.info(f"✓ Logged trial data to {data_file.name}: Trial={trial_number}, Label='{label}', RT={rt}, Clicks={clicks}")

            self._click_count = 0

        except Exception as e:
            logger.error(f"✗ Error logging trial data: {e}", exc_info=True)
