import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from rpi_logger.core.logging_utils import get_module_logger

from rpi_logger.modules.base import USBSerialDevice
from rpi_logger.modules.base.storage_utils import module_filename_prefix
from rpi_logger.core.commands import StatusMessage
from .constants import DRT_COMMANDS, DRT_RESPONSE_TYPES, ISO_PRESET_CONFIG


class DRTHandler:
    def __init__(self, device: USBSerialDevice, port: str, output_dir: Path, system: Optional[Any] = None):
        self.device = device
        self.port = port
        self.output_dir = output_dir
        self.system = system
        self._read_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._data_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
        self._config_future: Optional[asyncio.Future] = None
        self._click_count = 0
        self._buffered_trial_data: Optional[Dict[str, Any]] = None
        self.logger = get_module_logger("DRTHandler")

    def set_data_callback(self, callback: Callable[[str, str, Dict[str, Any]], None]):
        self._data_callback = callback

    async def start(self):
        if self._running:
            return

        self._running = True
        loop = asyncio.get_running_loop()
        self._loop = loop
        self._read_task = loop.create_task(self._read_loop())
        self.logger.info("Started DRT handler for %s", self.port)

    async def stop(self):
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
                    future = asyncio.run_coroutine_threadsafe(self._cancel_read_task(task), origin_loop)
                    try:
                        await asyncio.wrap_future(future)
                    except RuntimeError as exc:
                        self.logger.warning(
                            "Failed to await read loop task for %s on original loop: %s",
                            self.port,
                            exc,
                        )
                else:
                    self.logger.debug(
                        "Read loop task loop already stopped for %s; cancelling without await",
                        self.port,
                    )
                    task.cancel()
            else:
                await self._cancel_read_task(task)

        self._loop = None
        self.logger.info("Stopped DRT handler for %s", self.port)

    async def _cancel_read_task(self, task: asyncio.Task):
        try:
            task.cancel()
            await task
        except asyncio.CancelledError:
            pass

    async def send_command(self, command: str, value: Optional[str] = None) -> bool:
        if command not in DRT_COMMANDS:
            self.logger.warning("Unknown command: %s", command)
            return False

        cmd_string = DRT_COMMANDS[command]

        if value:
            message = f"{cmd_string} {value}\n\r"
        else:
            message = f"{cmd_string}\n\r"

        data = message.encode('utf-8')
        self.logger.info("Sending command to %s: %s", self.port, message.strip())
        success = await self.device.write(data)

        if success:
            self.logger.info("Command sent successfully to %s: %s", self.port, message.strip())
        else:
            self.logger.error("Failed to send command to %s: %s", self.port, message.strip())

        return success

    async def initialize_device(self) -> bool:
        self.logger.info("Initializing sDRT device on %s", self.port)
        return True

    async def close_device(self) -> bool:
        self.logger.info("Closing sDRT device on %s", self.port)
        return True

    async def start_experiment(self) -> bool:
        self._click_count = 0
        self._buffered_trial_data = None
        self.logger.info("Starting experiment on %s, reset click counter and buffer", self.port)
        return await self.send_command('exp_start')

    async def stop_experiment(self) -> bool:
        return await self.send_command('exp_stop')

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
        self.logger.debug("Requesting configuration from %s", self.port)

        self._config_future = asyncio.get_event_loop().create_future()

        success = await self.send_command('get_config')
        if not success:
            return None

        try:
            config_data = await asyncio.wait_for(self._config_future, timeout=2.0)
            return config_data
        except asyncio.TimeoutError:
            self.logger.warning("Timeout waiting for config response from %s", self.port)
            return None
        finally:
            self._config_future = None

    async def set_iso_params(self) -> bool:
        self.logger.info("Setting ISO preset parameters on %s", self.port)
        commands = [
            ('set_lowerISI', str(ISO_PRESET_CONFIG['lowerISI'])),
            ('set_upperISI', str(ISO_PRESET_CONFIG['upperISI'])),
            ('set_stimDur', str(ISO_PRESET_CONFIG['stimDur'])),
            ('set_intensity', str(ISO_PRESET_CONFIG['intensity'])),
        ]

        success = True
        for command, value in commands:
            result = await self.send_command(command, value)
            if not result:
                self.logger.error("Failed to send %s command to %s", command, self.port)
                success = False

        return success

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
            self.logger.error("Error in read loop for %s: %s", self.port, e)

    async def _process_response(self, response: str):
        self.logger.debug("Response from %s: %s", self.port, repr(response))

        try:
            parts = response.split('>')

            if not parts:
                return

            response_key = parts[0].lower()
            response_type = None
            data = {}

            for key, rtype in DRT_RESPONSE_TYPES.items():
                if key in response_key:
                    response_type = rtype
                    break

            if response_type == 'click':
                data = self._parse_click(parts)
            elif response_type == 'trial':
                data = self._parse_trial(parts)
                self._buffered_trial_data = data
                self.logger.debug("Buffered trial data, current clicks: %s", self._click_count)
            elif response_type == 'experiment_end':
                data = {'event': 'experiment_end', 'raw': response}
                if self._buffered_trial_data:
                    self.logger.debug("Experiment ended, writing buffered data")
                    await self._log_trial_data(self._buffered_trial_data)
                    self._buffered_trial_data = None
            elif response_type == 'stimulus':
                data = self._parse_stimulus(parts)
                if self._buffered_trial_data:
                    self.logger.debug("Stimulus detected, writing buffered data")
                    await self._log_trial_data(self._buffered_trial_data)
                    self._buffered_trial_data = None
            elif response_type == 'config':
                data = self._parse_config(parts)
                if self._config_future and not self._config_future.done():
                    self._config_future.set_result(data)
            else:
                data = {'raw': response}

            await self._dispatch_data_event(response_type or 'unknown', data)

            if self.system and getattr(self.system, 'enable_gui_commands', False):
                payload = {'port': self.port}
                if isinstance(data, dict):
                    for key, value in data.items():
                        if key != 'raw':
                            payload[key] = value
                if response_type:
                    payload.setdefault('event', response_type)
                StatusMessage.send('drt_event', payload)

        except Exception as e:
            self.logger.error("Error processing response from %s: %s", self.port, e)

    async def _dispatch_data_event(self, event_type: str, data: Dict[str, Any]) -> None:
        if not self._data_callback:
            return

        try:
            if asyncio.iscoroutinefunction(self._data_callback):
                await self._data_callback(self.port, event_type, data)
            else:
                self._data_callback(self.port, event_type, data)
        except Exception as exc:
            self.logger.error("Error in data callback for %s: %s", self.port, exc)

    def _parse_click(self, parts: list) -> Dict[str, Any]:
        value = parts[1] if len(parts) > 1 else ''
        self._click_count += 1
        self.logger.debug("Click detected on %s, total clicks: %s", self.port, self._click_count)
        return {
            'event': 'click',
            'value': value,
            'click_count': self._click_count,
            'raw': '>'.join(parts)
        }

    def _parse_trial(self, parts: list) -> Dict[str, Any]:
        data = {
            'event': 'trial',
            'responses': self._click_count,
            'raw': '>'.join(parts)
        }

        if len(parts) > 1 and parts[1]:
            try:
                values = parts[1].split(',')
                if len(values) >= 3:
                    data['timestamp'] = int(values[0]) if values[0] else None
                    data['trial_number'] = int(values[1]) if values[1] else None
                    data['reaction_time'] = float(values[2]) if values[2] else None
            except (ValueError, IndexError) as e:
                self.logger.warning("Could not parse trial data: %s", e)

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
                        self.logger.warning("Could not parse config value for %s: %s", key, value)
                        config_data[key] = value

        return config_data

    async def _log_trial_data(self, data: Dict[str, Any]):
        try:
            self.logger.info("_log_trial_data called, output_dir=%s", self.output_dir)
            await asyncio.to_thread(self.output_dir.mkdir, parents=True, exist_ok=True)

            trial_number = self._determine_trial_number(data)
            prefix = module_filename_prefix(self.output_dir, "DRT", trial_number, code="DRT")
            port_name = self.port.lstrip('/').replace('/', '_').replace('\\', '_').lower()
            data_file = self.output_dir / f"{prefix}_{port_name}.csv"

            file_exists = await asyncio.to_thread(data_file.exists)

            if not file_exists:
                def write_header():
                    with open(data_file, 'w', encoding='utf-8') as f:
                        f.write("Device ID, Label, Unix time in UTC, Milliseconds Since Record, Trial Number, Responses, Reaction Time\n")

                await asyncio.to_thread(write_header)
                self.logger.info("Created DRT data file: %s", data_file.name)

            port_clean = self.port.lstrip('/').replace('/', '_').replace('\\', '_')
            device_id = f"sDRT_{port_clean}"

            if self.system and hasattr(self.system, 'trial_label') and self.system.trial_label:
                label = self.system.trial_label
            else:
                label = str(trial_number)

            unix_time = int(datetime.now().timestamp())
            device_timestamp = data.get('timestamp', '')
            rt_raw = data.get('reaction_time', '')

            if rt_raw in ('', None):
                rt = ''
            else:
                try:
                    rt = int(float(rt_raw))
                except (TypeError, ValueError):
                    rt = rt_raw

            clicks = self._click_count
            if rt == -1 or rt == '-1':
                clicks = 0

            line = f"{device_id}, {label}, {unix_time}, {device_timestamp}, {trial_number}, {clicks}, {rt}\n"

            def append_line():
                with open(data_file, 'a', encoding='utf-8') as f:
                    f.write(line)

            await asyncio.to_thread(append_line)
            self.logger.debug("Logged trial: T=%s, RT=%s, Clicks=%s", trial_number, rt, clicks)

            log_payload = {
                'device_id': device_id,
                'label': label,
                'unix_time': unix_time,
                'device_timestamp': device_timestamp,
                'trial_number': trial_number,
                'responses': clicks,
                'reaction_time': rt,
                'raw': line.strip(),
                'line': line,
                'file_path': str(data_file),
            }

            await self._dispatch_data_event('trial_logged', log_payload)

            self._click_count = 0

        except Exception as e:
            self.logger.error("Error logging trial data: %s", e, exc_info=True)

    def _determine_trial_number(self, data: Dict[str, Any]) -> int:
        candidate = None
        if self.system is not None:
            candidate = getattr(self.system, "active_trial_number", None)
            if not candidate and hasattr(self.system, "model"):
                model = getattr(self.system, "model")
                candidate = getattr(model, "trial_number", None)
        if not candidate:
            candidate = data.get('trial_number')
        try:
            numeric = int(candidate)
        except (TypeError, ValueError):
            numeric = 0
        return numeric if numeric and numeric > 0 else 1
