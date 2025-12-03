"""wVOG protocol implementation for wireless VOG devices.

Protocol verified against actual hardware on 2025-12-02.
Firmware reference: RS_Logger/RSLogger/Firmware/wVOG_FW/wVOG/controller.py
"""

from typing import Dict, Optional
from rpi_logger.core.logging_utils import get_module_logger

from .base_protocol import (
    BaseVOGProtocol,
    VOGDataPacket,
    VOGResponse,
    ResponseType,
)
from ..constants import WVOG_BAUD


class WVOGProtocol(BaseVOGProtocol):
    """Protocol implementation for wVOG (wireless) devices.

    wVOG uses a MicroPython Pyboard controller with the following protocol:
    - Command format: cmd or cmd>val (no delimiters)
    - Response format: keyword>value
    - Dual lens control (A, B, or X=both)
    - Battery monitoring
    - RTC support

    USB Connection:
    - VID: 0xf057, PID: 0x08AE
    - Baud: 57600
    - Device shows as "MicroPython Pyboard Virtual Comm Port in FS Mode"
    """

    # wVOG Commands (MicroPython protocol)
    # Verified from hardware testing 2025-12-02
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

    # Response keywords and their types
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

    # Configuration keys in cfg response
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

    CSV_HEADER_STRING = "Device ID, Label, Unix time in UTC, Milliseconds Since Record, Trial Number, Shutter Open, Shutter Closed, Total, Lens, Battery Percent"

    def __init__(self):
        self.logger = get_module_logger("WVOGProtocol")

    @property
    def device_type(self) -> str:
        return 'wvog'

    @property
    def baudrate(self) -> int:
        return WVOG_BAUD

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
        """Format a command for wVOG transmission.

        Args:
            command: Command key from COMMANDS
            value: Optional value for set commands

        Returns:
            Encoded bytes with newline terminator
        """
        if command not in self.COMMANDS:
            self.logger.warning("Unknown wVOG command: %s", command)
            return b''

        cmd_string = self.COMMANDS[command]

        # Substitute value if needed
        if value is not None:
            if '{key}' in cmd_string and '{value}' in cmd_string:
                # set_config format: set>{key},{value}
                # value should be in format "key,val"
                cmd_string = cmd_string.replace('{key},{value}', value)
            elif '{value}' in cmd_string:
                cmd_string = cmd_string.format(value=value)

        return f"{cmd_string}\n".encode('utf-8')

    def parse_response(self, response: str) -> Optional[VOGResponse]:
        """Parse wVOG response.

        wVOG responses are in format: keyword>value or just keyword

        Args:
            response: Raw response string

        Returns:
            VOGResponse or None
        """
        response = response.strip()

        if not response:
            return None

        # Parse keyword>value format
        if '>' in response:
            parts = response.split('>', 1)
            keyword = parts[0]
            value = parts[1] if len(parts) > 1 else ''
        else:
            keyword = response
            value = ''

        # Find matching response type
        response_type = self.RESPONSE_TYPES.get(keyword, ResponseType.UNKNOWN)

        if response_type == ResponseType.UNKNOWN:
            self.logger.debug("Unrecognized wVOG response: %s", response)
            return None

        data = {}

        if response_type == ResponseType.STIMULUS:
            try:
                data['state'] = int(value)
            except ValueError:
                data['state'] = value
            # Track which lens for a/b/x responses
            if keyword in ('a', 'b', 'x'):
                data['lens'] = keyword.upper()

        elif response_type == ResponseType.BATTERY:
            try:
                data['percent'] = int(value)
            except ValueError:
                data['percent'] = 0

        elif response_type == ResponseType.CONFIG:
            # Parse config string: key:val,key:val,...
            data['config'] = self._parse_config_string(value)

        elif response_type == ResponseType.RTC:
            # Parse RTC: Y,M,D,dow,H,M,S,ss
            data['rtc'] = self._parse_rtc_string(value)

        return VOGResponse(
            response_type=response_type,
            keyword=keyword,
            value=value,
            raw=response,
            data=data,
        )

    def _parse_config_string(self, value: str) -> Dict[str, str]:
        """Parse wVOG config string.

        Format: key:val,key:val,...
        Example: clr:100,cls:1500,dbc:20,srt:1,opn:1500,dta:0,drk:0,typ:cycle
        """
        config = {}
        if not value:
            return config

        pairs = value.split(',')
        for pair in pairs:
            if ':' in pair:
                k, v = pair.split(':', 1)
                # Map short key to long name if known
                long_name = self.CONFIG_KEYS.get(k, k)
                config[long_name] = v
                config[k] = v  # Also store short key

        return config

    def _parse_rtc_string(self, value: str) -> Dict[str, int]:
        """Parse wVOG RTC string.

        Format: Y,M,D,dow,H,M,S,ss
        Example: 2025,12,2,1,14,30,0,0
        """
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
        """Parse wVOG data response.

        Data format: trial_num,shutter_open,shutter_closed,total_ms,lens,battery_pct,device_unix_time
        Example: 1,1999,1500,3499,X,85,1733150423

        Args:
            value: Data value string
            device_id: Device identifier

        Returns:
            VOGDataPacket or None
        """
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
                    device_unix_time=int(parts[6]) if parts[6] else 0,
                )
            elif len(parts) >= 3:
                # Minimal data format
                return VOGDataPacket(
                    device_id=device_id,
                    trial_number=int(parts[0]) if parts[0] else 0,
                    shutter_open=int(parts[1]) if parts[1] else 0,
                    shutter_closed=int(parts[2]) if parts[2] else 0,
                )
        except (ValueError, IndexError) as e:
            self.logger.warning("Could not parse wVOG data: %s - %s", value, e)

        return None

    def get_command_keys(self) -> Dict[str, str]:
        """Return command mapping."""
        return self.COMMANDS.copy()

    def to_extended_csv_row(
        self,
        packet: VOGDataPacket,
        label: str,
        unix_time: int,
        ms_since_record: int
    ) -> str:
        """Format wVOG data as extended CSV row.

        Args:
            packet: Data packet
            label: Trial label
            unix_time: Host system unix timestamp
            ms_since_record: Milliseconds since recording started

        Returns:
            CSV formatted string (no newline)
        """
        return (f"{packet.device_id}, {label}, {unix_time}, {ms_since_record}, "
                f"{packet.trial_number}, {packet.shutter_open}, {packet.shutter_closed}, "
                f"{packet.shutter_total}, {packet.lens}, {packet.battery_percent}")

    # ------------------------------------------------------------------
    # Polymorphic methods (Phase 7 cleanup)
    # ------------------------------------------------------------------

    def get_config_commands(self) -> list:
        """Return list of commands to retrieve wVOG configuration."""
        # wVOG returns all config in one command
        return ['get_config']

    def format_set_config(self, param: str, value: str) -> tuple:
        """Format a config set operation for wVOG.

        wVOG uses 'set_config' command with 'param,value' as argument.
        """
        return ('set_config', f'{param},{value}')

    def update_config_from_response(self, response, config: dict) -> None:
        """Update config from wVOG response (all values at once)."""
        config.update(response.data.get('config', {}))

    def get_extended_packet_data(self, packet) -> dict:
        """Return wVOG extended packet data."""
        return {
            'shutter_total': packet.shutter_total,
            'lens': packet.lens,
            'battery_percent': packet.battery_percent,
            'device_unix_time': packet.device_unix_time,
        }

    def format_csv_row(self, packet, label: str, unix_time: int, ms_since_record: int) -> str:
        """Format wVOG packet as CSV row (extended format)."""
        return self.to_extended_csv_row(packet, label, unix_time, ms_since_record)
