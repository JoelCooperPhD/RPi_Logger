"""Abstract base protocol for VOG devices."""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum


class ResponseType(Enum):
    """Types of responses from VOG devices."""
    VERSION = 'version'
    CONFIG = 'config'
    STIMULUS = 'stimulus'
    DATA = 'data'
    BATTERY = 'battery'
    RTC = 'rtc'
    EXPERIMENT = 'experiment'
    TRIAL = 'trial'
    UNKNOWN = 'unknown'


@dataclass
class VOGDataPacket:
    """Universal data packet from VOG device.

    Contains all fields that may be present from either sVOG or wVOG devices.
    Device-specific fields will be 0 or default if not applicable.
    """
    device_id: str
    trial_number: int
    shutter_open: int        # ms shutter was open/clear
    shutter_closed: int      # ms shutter was closed/opaque
    shutter_total: int = 0   # Total ms (wVOG only)
    lens: str = 'X'          # Which lens: 'A', 'B', or 'X' (both) - wVOG only
    battery_percent: int = 0  # Battery SOC - wVOG only
    device_unix_time: int = 0  # Device's RTC timestamp - wVOG only

    def to_csv_row(self, label: str, unix_time: int, ms_since_record: int) -> str:
        """Format as CSV row for logging.

        Args:
            label: Trial label
            unix_time: Host system unix timestamp
            ms_since_record: Milliseconds since recording started

        Returns:
            CSV formatted string (no newline)
        """
        return (f"{self.device_id}, {label}, {unix_time}, {ms_since_record}, "
                f"{self.trial_number}, {self.shutter_open}, {self.shutter_closed}")


@dataclass
class VOGResponse:
    """Parsed response from a VOG device."""
    response_type: ResponseType
    keyword: str
    value: str
    raw: str
    data: Dict[str, Any] = field(default_factory=dict)


class BaseVOGProtocol(ABC):
    """Abstract base class for VOG device protocols.

    Subclasses implement device-specific command formatting and response parsing
    while presenting a unified interface to the handler.
    """

    @property
    @abstractmethod
    def device_type(self) -> str:
        """Return device type identifier ('svog' or 'wvog')."""
        pass

    @property
    @abstractmethod
    def supports_dual_lens(self) -> bool:
        """Return True if device supports dual lens control (A/B/X)."""
        pass

    @property
    @abstractmethod
    def supports_battery(self) -> bool:
        """Return True if device reports battery status."""
        pass

    @property
    @abstractmethod
    def csv_header(self) -> str:
        """Return the CSV header for this device type."""
        pass

    @abstractmethod
    def format_command(self, command: str, value: Optional[str] = None) -> bytes:
        """Format a command for transmission to device.

        Args:
            command: Command key (e.g., 'exp_start', 'get_config')
            value: Optional value for set commands

        Returns:
            Encoded bytes ready to send to device
        """
        pass

    @abstractmethod
    def parse_response(self, response: str) -> Optional[VOGResponse]:
        """Parse device response into structured format.

        Args:
            response: Raw response string from device

        Returns:
            VOGResponse object or None if response is not recognized
        """
        pass

    @abstractmethod
    def parse_data_response(self, value: str, device_id: str) -> Optional[VOGDataPacket]:
        """Parse a data response into a VOGDataPacket.

        Args:
            value: The value portion of the data response
            device_id: Device identifier for the packet

        Returns:
            VOGDataPacket or None if parsing fails
        """
        pass

    @abstractmethod
    def get_command_keys(self) -> Dict[str, str]:
        """Return mapping of command keys to raw command strings."""
        pass

    def has_command(self, command: str) -> bool:
        """Check if a command is supported by this protocol."""
        return command in self.get_command_keys()

    # ------------------------------------------------------------------
    # Polymorphic methods to eliminate device_type branching
    # ------------------------------------------------------------------

    @abstractmethod
    def get_config_commands(self) -> list:
        """Return list of commands to retrieve device configuration.

        For sVOG: Returns list of individual get commands.
        For wVOG: Returns single 'get_config' command.
        """
        pass

    @abstractmethod
    def format_set_config(self, param: str, value: str) -> Tuple[str, Optional[str]]:
        """Format a config set operation for this protocol.

        Args:
            param: Parameter name (e.g., 'max_open', 'debounce')
            value: Value to set

        Returns:
            Tuple of (command_key, command_value) for send_command()
        """
        pass

    @abstractmethod
    def update_config_from_response(self, response: VOGResponse, config: Dict[str, Any]) -> None:
        """Update config dict from a parsed response.

        For sVOG: Sets config[keyword] = value
        For wVOG: Updates config with all values from response

        Args:
            response: Parsed VOGResponse with CONFIG type
            config: Config dict to update in place
        """
        pass

    @abstractmethod
    def get_extended_packet_data(self, packet: VOGDataPacket) -> Dict[str, Any]:
        """Get device-specific extended data fields from a packet.

        Args:
            packet: Data packet from device

        Returns:
            Dict of additional fields (empty for sVOG, battery/lens/etc for wVOG)
        """
        pass

    @abstractmethod
    def format_csv_row(self, packet: VOGDataPacket, label: str, unix_time: int, ms_since_record: int) -> str:
        """Format packet as CSV row for this device type.

        Args:
            packet: Data packet from device
            label: Trial label
            unix_time: Host system unix timestamp
            ms_since_record: Milliseconds since recording started

        Returns:
            CSV formatted string (no newline)
        """
        pass
