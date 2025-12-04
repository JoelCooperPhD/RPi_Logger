"""
VOG Device Types and Registry

Defines device types, specifications, and registry for all supported VOG variants:
- sVOG (USB only, wired Arduino-based)
- wVOG (USB, direct connection)
- wVOG (Wireless via XBee)
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional


class VOGDeviceType(Enum):
    """Enumeration of supported VOG device types."""
    SVOG = "sVOG"
    WVOG_USB = "wVOG_USB"
    WVOG_WIRELESS = "wVOG_Wireless"


@dataclass(frozen=True)
class DeviceSpec:
    """
    Specification for a VOG device type.

    Attributes:
        vid: USB Vendor ID
        pid: USB Product ID
        name: Human-readable device name
        baudrate: Serial communication baudrate
    """
    vid: int
    pid: int
    name: str
    baudrate: int = 57600

    def matches_port(self, port_info) -> bool:
        """
        Check if a serial port matches this device specification.

        Args:
            port_info: A serial.tools.list_ports.ListPortInfo object

        Returns:
            True if the port's VID/PID match this device spec
        """
        return (
            port_info.vid == self.vid and
            port_info.pid == self.pid
        )


# Device specifications for USB-connected devices
# sVOG: Arduino-based wired device
# wVOG_USB: MicroPython Pyboard direct USB connection
DEVICE_REGISTRY: Dict[VOGDeviceType, DeviceSpec] = {
    VOGDeviceType.SVOG: DeviceSpec(
        vid=0x16C0,
        pid=0x0483,
        name='sVOG',
        baudrate=115200
    ),
    VOGDeviceType.WVOG_USB: DeviceSpec(
        vid=0xF057,
        pid=0x08AE,
        name='wVOG',
        baudrate=57600
    ),
}

# XBee dongle specification (used for wireless wVOG)
XBEE_DONGLE = DeviceSpec(
    vid=0x0403,
    pid=0x6015,
    name='XBee',
    baudrate=57600
)


def identify_device_type(port_info) -> Optional[VOGDeviceType]:
    """
    Identify the VOG device type from a serial port.

    Args:
        port_info: A serial.tools.list_ports.ListPortInfo object

    Returns:
        The matching VOGDeviceType, or None if not a known VOG device
    """
    for device_type, spec in DEVICE_REGISTRY.items():
        if spec.matches_port(port_info):
            return device_type
    return None


def is_xbee_dongle(port_info) -> bool:
    """
    Check if a serial port is an XBee dongle.

    Args:
        port_info: A serial.tools.list_ports.ListPortInfo object

    Returns:
        True if the port is an XBee dongle
    """
    return XBEE_DONGLE.matches_port(port_info)


def get_device_spec(device_type: VOGDeviceType) -> Optional[DeviceSpec]:
    """
    Get the device specification for a given device type.

    Args:
        device_type: The VOG device type

    Returns:
        The DeviceSpec for USB-based types, None for wireless
    """
    return DEVICE_REGISTRY.get(device_type)


def device_type_from_string(type_str: str) -> Optional[VOGDeviceType]:
    """
    Convert a string device type to VOGDeviceType enum.

    Args:
        type_str: String like 'svog', 'wvog', 'wvog_usb', 'wvog_wireless'

    Returns:
        The matching VOGDeviceType, or None if not recognized
    """
    type_lower = type_str.lower().strip()
    if type_lower == 'svog':
        return VOGDeviceType.SVOG
    elif type_lower in ('wvog', 'wvog_usb'):
        return VOGDeviceType.WVOG_USB
    elif type_lower == 'wvog_wireless':
        return VOGDeviceType.WVOG_WIRELESS
    return None


def device_type_to_legacy_string(device_type: VOGDeviceType) -> str:
    """
    Convert VOGDeviceType to legacy string format used in existing code.

    Args:
        device_type: The VOGDeviceType enum value

    Returns:
        Legacy string ('svog' or 'wvog')
    """
    if device_type == VOGDeviceType.SVOG:
        return 'svog'
    return 'wvog'
