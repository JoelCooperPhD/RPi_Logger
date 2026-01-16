"""Abstract base protocol for VOG devices."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum


class ResponseType(Enum):
    """VOG device response types."""
    VERSION, CONFIG, STIMULUS, DATA, BATTERY, RTC, EXPERIMENT, TRIAL, UNKNOWN = \
        'version', 'config', 'stimulus', 'data', 'battery', 'rtc', 'experiment', 'trial', 'unknown'


@dataclass
class VOGDataPacket:
    """Universal data packet from VOG device (sVOG/wVOG). Device-specific fields default to 0."""
    device_id: str
    trial_number: int
    shutter_open: int        # ms open/clear
    shutter_closed: int      # ms closed/opaque
    shutter_total: int = 0   # Total ms (wVOG)
    lens: str = 'X'          # 'A', 'B', or 'X' (wVOG)
    battery_percent: int = 0  # Battery SOC (wVOG)
    device_unix_time: int = 0  # RTC timestamp (wVOG)

    def to_csv_row(self, label: str, unix_time: int, ms_since_record: int) -> str:
        """Format as CSV row (device_id, label, unix_time, ms_since_record, trial, open, closed)."""
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
    """Base class for VOG protocols. Subclasses implement device-specific formatting/parsing."""

    @property
    @abstractmethod
    def device_type(self) -> str:
        """Device type identifier ('svog' or 'wvog')."""

    @property
    @abstractmethod
    def supports_dual_lens(self) -> bool:
        """True if device supports dual lens control (A/B/X)."""

    @property
    @abstractmethod
    def supports_battery(self) -> bool:
        """True if device reports battery status."""

    @property
    @abstractmethod
    def csv_header(self) -> str:
        """CSV header for this device type."""

    @abstractmethod
    def format_command(self, command: str, value: Optional[str] = None) -> bytes:
        """Format command for device transmission. Returns encoded bytes."""

    @abstractmethod
    def parse_response(self, response: str) -> Optional[VOGResponse]:
        """Parse device response. Returns VOGResponse or None."""

    @abstractmethod
    def parse_data_response(self, value: str, device_id: str) -> Optional[VOGDataPacket]:
        """Parse data response into VOGDataPacket or None."""

    @abstractmethod
    def get_command_keys(self) -> Dict[str, str]:
        """Mapping of command keys to raw command strings."""

    def has_command(self, command: str) -> bool:
        """Check if command is supported."""
        return command in self.get_command_keys()

    @abstractmethod
    def get_config_commands(self) -> list:
        """Commands to retrieve config (sVOG: list of gets, wVOG: single get_config)."""

    @abstractmethod
    def format_set_config(self, param: str, value: str) -> Tuple[str, Optional[str]]:
        """Format config set operation as (command_key, command_value) for send_command()."""

    @abstractmethod
    def update_config_from_response(self, response: VOGResponse, config: Dict[str, Any]) -> None:
        """Update config dict from response (sVOG: one value, wVOG: all values)."""

    @abstractmethod
    def get_extended_packet_data(self, packet: VOGDataPacket) -> Dict[str, Any]:
        """Device-specific extended data (empty for sVOG, battery/lens/etc for wVOG)."""

    @abstractmethod
    def format_csv_row(self, packet: VOGDataPacket, label: str,
                      record_time_unix: float, record_time_mono: float) -> List[Any]:
        """Format packet as CSV row (returns list of values for csv.writer)."""
