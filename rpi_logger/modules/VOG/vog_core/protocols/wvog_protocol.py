"""wVOG protocol (wireless VOG). Verified against hardware 2025-12-02."""

from typing import Dict, Optional
from rpi_logger.core.logging_utils import get_module_logger

from .base_protocol import (
    BaseVOGProtocol,
    VOGDataPacket,
    VOGResponse,
    ResponseType,
)


class WVOGProtocol(BaseVOGProtocol):
    """wVOG (wireless) protocol. MicroPython Pyboard, cmd>val format, dual lens, battery, RTC, 57600 baud."""

    COMMANDS = {
        # Experiment control
        'exp_start': 'exp>1',
        'exp_stop': 'exp>0',
        'trial_start': 'trl>1',
        'trial_stop': 'trl>0',

        # Lens control (a=left, b=right, x=both)
        # Value: 1=clear/open, 0=opaque/closed
        'lens_open_a': 'a>1',
        'lens_close_a': 'a>0',
        'lens_open_b': 'b>1',
        'lens_close_b': 'b>0',
        'lens_open_x': 'x>1',
        'lens_close_x': 'x>0',

        # Legacy peek commands (map to x lens)
        'peek_open': 'x>1',
        'peek_close': 'x>0',

        # Configuration
        'get_config': 'cfg',
        'set_config': 'set>{key},{value}',

        # Status
        'get_battery': 'bat',
        'get_rtc': 'rtc',
        'set_rtc': 'rtc>{value}',  # Format: Y,M,D,dow,H,M,S,ss
    }

    # Response format: keyword>value
    RESPONSE_TYPES = {
        'cfg': ResponseType.CONFIG,
        'bty': ResponseType.BATTERY,
        'rtc': ResponseType.RTC,
        'stm': ResponseType.STIMULUS,
        'a': ResponseType.STIMULUS,    # Lens A state (left)
        'b': ResponseType.STIMULUS,    # Lens B state (right)
        'x': ResponseType.STIMULUS,    # Both lenses state
        'dta': ResponseType.DATA,
        'exp': ResponseType.EXPERIMENT,
        'trl': ResponseType.TRIAL,
        'end': ResponseType.DATA,  # End marker before data
    }

    # Format: cfg>key:val,key:val,...
    CONFIG_KEYS = {
        'clr': 'clear_opacity',      # Clear/open opacity (0-100)
        'cls': 'close_time',         # Close time in ms
        'dbc': 'debounce',           # Debounce time in ms
        'srt': 'start_state',        # Start state (0=opaque, 1=clear)
        'opn': 'open_time',          # Open time in ms
        'dta': 'data_mode',          # Data mode
        'drk': 'dark_opacity',       # Dark/opaque opacity (0-100)
        'typ': 'experiment_type',    # cycle, peek, eblind, direct
    }

    CSV_HEADER_STRING = "trial,module,device_id,label,record_time_unix,record_time_mono,shutter_open,shutter_closed,shutter_total,lens,battery_percent"

    def __init__(self):
        self.logger = get_module_logger("WVOGProtocol")

    @property
    def device_type(self) -> str:
        return 'wvog'

    @property
    def supports_dual_lens(self) -> bool:
        return True

    @property
    def supports_battery(self) -> bool:
        return True

    @property
    def csv_header(self) -> str:
        return self.CSV_HEADER_STRING

    def format_command(self, command: str, value: Optional[str] = None) -> bytes:
        """Format wVOG command with optional value substitution."""
        if command not in self.COMMANDS:
            self.logger.debug("Unknown wVOG command: %s", command)
            return b''
        cmd_string = self.COMMANDS[command]
        if value is not None:
            if '{key}' in cmd_string and '{value}' in cmd_string:
                cmd_string = cmd_string.replace('{key},{value}', value)
            elif '{value}' in cmd_string:
                cmd_string = cmd_string.format(value=value)
        return f"{cmd_string}\n".encode('utf-8')

    def parse_response(self, response: str) -> Optional[VOGResponse]:
        """Parse wVOG response (keyword>value or keyword)."""
        response = response.strip()
        if not response:
            return None

        # Parse keyword>value format
        if '>' in response:
            parts = response.split('>', 1)
            keyword, value = parts[0], parts[1] if len(parts) > 1 else ''
        else:
            keyword, value = response, ''

        response_type = self.RESPONSE_TYPES.get(keyword, ResponseType.UNKNOWN)
        if response_type == ResponseType.UNKNOWN:
            return None

        data = {}
        if response_type == ResponseType.STIMULUS:
            try:
                data['state'] = int(value)
            except ValueError:
                data['state'] = value
            if keyword in ('a', 'b', 'x'):
                data['lens'] = keyword.upper()
        elif response_type == ResponseType.BATTERY:
            try:
                data['percent'] = int(value)
            except ValueError:
                data['percent'] = 0
        elif response_type == ResponseType.CONFIG:
            data['config'] = self._parse_config_string(value)
        elif response_type == ResponseType.RTC:
            data['rtc'] = self._parse_rtc_string(value)

        return VOGResponse(response_type, keyword, value, response, data)

    def _parse_config_string(self, value: str) -> Dict[str, str]:
        """Parse config string (format: key:val,key:val,...)."""
        config = {}
        if not value:
            return config
        for pair in value.split(','):
            if ':' in pair:
                k, v = pair.split(':', 1)
                long_name = self.CONFIG_KEYS.get(k, k)
                config[long_name] = v
                config[k] = v
        return config

    def _parse_rtc_string(self, value: str) -> Dict[str, int]:
        """Parse RTC string (format: Y,M,D,dow,H,M,S,ss)."""
        rtc = {}
        if not value:
            return rtc
        parts = value.split(',')
        keys = ['year', 'month', 'day', 'dow', 'hour', 'minute', 'second', 'subsecond']
        for i, key in enumerate(keys):
            if i < len(parts):
                try:
                    rtc[key] = int(parts[i])
                except ValueError:
                    rtc[key] = 0
        return rtc

    def parse_data_response(self, value: str, device_id: str) -> Optional[VOGDataPacket]:
        """Parse wVOG data (format: trial,open,closed,total,lens,battery,unix_time)."""
        try:
            parts = value.split(',')
            if len(parts) >= 7:
                return VOGDataPacket(
                    device_id=device_id,
                    trial_number=int(parts[0]) if parts[0] else 0,
                    shutter_open=int(parts[1]) if parts[1] else 0,
                    shutter_closed=int(parts[2]) if parts[2] else 0,
                    shutter_total=int(parts[3]) if parts[3] else 0,
                    lens=parts[4] if parts[4] else 'X',
                    battery_percent=int(parts[5]) if parts[5] else 0,
                    device_unix_time=int(parts[6]) if parts[6] else 0)
            elif len(parts) >= 3:
                return VOGDataPacket(
                    device_id=device_id,
                    trial_number=int(parts[0]) if parts[0] else 0,
                    shutter_open=int(parts[1]) if parts[1] else 0,
                    shutter_closed=int(parts[2]) if parts[2] else 0)
        except (ValueError, IndexError) as e:
            self.logger.warning("Could not parse wVOG data: %s - %s", value, e)
        return None

    def get_command_keys(self) -> Dict[str, str]:
        """Return command mapping."""
        return self.COMMANDS.copy()

    def get_config_commands(self) -> list:
        """Commands to retrieve wVOG config (single command returns all)."""
        return ['get_config']

    def format_set_config(self, param: str, value: str) -> tuple:
        """Format config set (wVOG uses 'set_config' with 'param,value')."""
        return ('set_config', f'{param},{value}')

    def update_config_from_response(self, response, config: dict) -> None:
        """Update config from wVOG response (all values at once)."""
        config.update(response.data.get('config', {}))

    def get_extended_packet_data(self, packet) -> dict:
        """wVOG extended packet data."""
        return {'shutter_total': packet.shutter_total, 'lens': packet.lens,
                'battery_percent': packet.battery_percent, 'device_unix_time': packet.device_unix_time}

    def format_csv_row(self, packet, label: str, record_time_unix: float,
                      record_time_mono: float) -> list:
        """Format wVOG CSV row (returns list of values for csv.writer)."""
        return [
            packet.trial_number, "VOG", packet.device_id, label,
            f"{record_time_unix:.6f}", f"{record_time_mono:.9f}",
            packet.shutter_open, packet.shutter_closed,
            packet.shutter_total, packet.lens, packet.battery_percent
        ]
