"""sVOG protocol implementation for wired VOG devices.

Protocol verified against RS_Logger firmware:
- RS_Logger/RSLogger/Firmware/sVOG_FW/embedded
- RS_Logger/RSLogger/hardware_io/sVOG_HI/sVOG_HIController.py

Firmware Version: 2.2 (10/12/2021)
"""

from typing import Dict, Optional
from rpi_logger.core.logging_utils import get_module_logger

from .base_protocol import (
    BaseVOGProtocol,
    VOGDataPacket,
    VOGResponse,
    ResponseType,
)


class SVOGProtocol(BaseVOGProtocol):
    """Protocol implementation for sVOG (wired) devices.

    sVOG uses an Arduino-based controller with the following protocol:
    - Command format: >cmd|val<<
    - Response format: keyword|value
    - Single lens control only
    - No battery monitoring
    - Baud rate: 115200
    """

    # sVOG Commands (Arduino protocol)
    # Format: >COMMAND|VALUE<<\n
    COMMANDS = {
        # Experiment control
        'exp_start': '>do_expStart|<<',
        'exp_stop': '>do_expStop|<<',
        'trial_start': '>do_trialStart|<<',
        'trial_stop': '>do_trialStop|<<',

        # Lens control (peek)
        'peek_open': '>do_peekOpen|<<',
        'peek_close': '>do_peekClose|<<',

        # Device information queries
        'get_device_name': '>get_deviceName|<<',
        'get_device_ver': '>get_deviceVer|<<',
        'get_device_date': '>get_deviceDate|<<',

        # Configuration get commands
        'get_config': '>get_config|<<',  # Returns all config values
        'get_config_name': '>get_configName|<<',
        'get_max_open': '>get_configMaxOpen|<<',
        'get_max_close': '>get_configMaxClose|<<',
        'get_debounce': '>get_configDebounce|<<',
        'get_click_mode': '>get_configClickMode|<<',
        'get_button_control': '>get_configButtonControl|<<',

        # Configuration set commands
        'set_config_name': '>set_configName|{val}<<',
        'set_max_open': '>set_configMaxOpen|{val}<<',
        'set_max_close': '>set_configMaxClose|{val}<<',
        'set_debounce': '>set_configDebounce|{val}<<',
        'set_click_mode': '>set_configClickMode|{val}<<',
        'set_button_control': '>set_configButtonControl|{val}<<',

        # Runtime state queries
        'get_trial_counter': '>get_trialCounter|<<',
        'get_open_elapsed': '>get_openElapsed|<<',
        'get_closed_elapsed': '>get_closedElapsed|<<',

        # Factory reset
        'factory_reset': '>do_factoryReset|<<',
    }

    # Response keywords and their types
    # Response format: keyword|value
    RESPONSE_TYPES = {
        # Device info
        'deviceName': ResponseType.VERSION,
        'deviceVer': ResponseType.VERSION,
        'deviceDate': ResponseType.VERSION,

        # Configuration values
        'configName': ResponseType.CONFIG,
        'configMaxOpen': ResponseType.CONFIG,
        'configMaxClose': ResponseType.CONFIG,
        'configDebounce': ResponseType.CONFIG,
        'configClickMode': ResponseType.CONFIG,
        'configButtonControl': ResponseType.CONFIG,

        # Runtime state
        'trialCounter': ResponseType.CONFIG,
        'openElapsed': ResponseType.CONFIG,
        'closedElapsed': ResponseType.CONFIG,

        # Stimulus state (lens open/close)
        'stm': ResponseType.STIMULUS,

        # Trial data
        'data': ResponseType.DATA,

        # Button events
        'btn': ResponseType.STIMULUS,  # btn|1 or btn|0
    }

    # Simple acknowledgment responses (no pipe separator)
    SIMPLE_RESPONSES = {
        'expStart': ResponseType.EXPERIMENT,
        'expStop': ResponseType.EXPERIMENT,
        'trialStart': ResponseType.TRIAL,
        'Click': ResponseType.STIMULUS,
    }

    CSV_HEADER_STRING = "trial,module,device_id,label,record_time_unix,record_time_mono,shutter_open,shutter_closed"

    def __init__(self):
        self.logger = get_module_logger("SVOGProtocol")

    @property
    def device_type(self) -> str:
        return 'svog'

    @property
    def supports_dual_lens(self) -> bool:
        return False

    @property
    def supports_battery(self) -> bool:
        return False

    @property
    def csv_header(self) -> str:
        return self.CSV_HEADER_STRING

    def format_command(self, command: str, value: Optional[str] = None) -> bytes:
        """Format a command for sVOG transmission.

        Args:
            command: Command key from COMMANDS
            value: Optional value for set commands

        Returns:
            Encoded bytes with newline terminator
        """
        if command not in self.COMMANDS:
            self.logger.warning("Unknown sVOG command: %s", command)
            return b''

        cmd_string = self.COMMANDS[command]

        # Substitute value if needed
        if value is not None and '{val}' in cmd_string:
            cmd_string = cmd_string.format(val=value)

        return f"{cmd_string}\n".encode('utf-8')

    def parse_response(self, response: str) -> Optional[VOGResponse]:
        """Parse sVOG response.

        sVOG responses can be:
        - Pipe-delimited: keyword|value (e.g., stm|1, data|1,3000,1500)
        - Simple: keyword (e.g., expStart, Click)

        Args:
            response: Raw response string

        Returns:
            VOGResponse or None
        """
        response = response.strip()

        if not response:
            return None

        # Check for simple responses first (no pipe)
        if response in self.SIMPLE_RESPONSES:
            response_type = self.SIMPLE_RESPONSES[response]
            data = {}

            if response == 'Click':
                data['state'] = 'click'
                data['button_event'] = True

            return VOGResponse(
                response_type=response_type,
                keyword=response,
                value='',
                raw=response,
                data=data,
            )

        # Parse pipe-delimited responses
        if '|' not in response:
            self.logger.debug("Unrecognized sVOG response (no pipe): %s", response)
            return None

        parts = response.split('|', 1)
        keyword = parts[0]
        value = parts[1] if len(parts) > 1 else ''

        # Find matching response type
        response_type = self.RESPONSE_TYPES.get(keyword, ResponseType.UNKNOWN)

        if response_type == ResponseType.UNKNOWN:
            self.logger.debug("Unrecognized sVOG response keyword: %s", keyword)
            return None

        data = {}

        if response_type == ResponseType.STIMULUS:
            # stm|1 or stm|0 for lens state
            # btn|1 or btn|0 for button state
            try:
                data['state'] = int(value)
            except ValueError:
                data['state'] = value

            if keyword == 'btn':
                data['button_event'] = True
                data['button_state'] = data['state']

        return VOGResponse(
            response_type=response_type,
            keyword=keyword,
            value=value,
            raw=response,
            data=data,
        )

    def parse_data_response(self, value: str, device_id: str) -> Optional[VOGDataPacket]:
        """Parse sVOG data response.

        Data format: TRIAL_NUMBER,TIME_OPEN_ELAPSED,TIME_CLOSE_ELAPSED
        Example: 5,3000,1500

        Args:
            value: Data value string (after 'data|')
            device_id: Device identifier

        Returns:
            VOGDataPacket or None
        """
        try:
            parts = value.split(',')
            if len(parts) >= 3:
                return VOGDataPacket(
                    device_id=device_id,
                    trial_number=int(parts[0].strip()) if parts[0].strip() else 0,
                    shutter_open=int(parts[1].strip()) if parts[1].strip() else 0,
                    shutter_closed=int(parts[2].strip()) if parts[2].strip() else 0,
                    lens='X',  # sVOG has single lens
                )
        except (ValueError, IndexError) as e:
            self.logger.warning("Could not parse sVOG data: %s - %s", value, e)

        return None

    def get_command_keys(self) -> Dict[str, str]:
        """Return command mapping."""
        return self.COMMANDS.copy()

    # ------------------------------------------------------------------
    # Polymorphic methods
    # ------------------------------------------------------------------

    def get_config_commands(self) -> list:
        """Return list of commands to retrieve sVOG configuration."""
        return [
            'get_device_ver',
            'get_config_name',
            'get_max_open',
            'get_max_close',
            'get_debounce',
            'get_click_mode',
            'get_button_control',
        ]

    def format_set_config(self, param: str, value: str) -> tuple:
        """Format a config set operation for sVOG.

        sVOG uses separate commands like 'set_max_open' with value as argument.
        """
        command = f'set_{param}'
        if command not in self.COMMANDS:
            return (None, None)  # Unknown parameter
        return (command, value)

    def update_config_from_response(self, response, config: dict) -> None:
        """Update config from sVOG response (one value at a time)."""
        config[response.keyword] = response.value

    def get_extended_packet_data(self, packet) -> dict:
        """sVOG has no extended packet data."""
        return {}

    def format_csv_row(
        self,
        packet,
        label: str,
        record_time_unix: float,
        record_time_mono: float,
    ) -> str:
        """Format sVOG packet as CSV row."""
        return (
            f"{packet.trial_number},VOG,{packet.device_id},{label},"
            f"{record_time_unix:.6f},{record_time_mono:.9f},"
            f"{packet.shutter_open},{packet.shutter_closed}"
        )
