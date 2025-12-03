"""
DRT Device Types and Registry

Defines device types, specifications, and registry for all supported DRT variants:
- sDRT (USB only)
- wDRT (USB)
- wDRT (Wireless via XBee)
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional


class DRTDeviceType(Enum):
    """Enumeration of supported DRT device types."""
    SDRT = "sDRT"
    WDRT_USB = "wDRT_USB"
    WDRT_WIRELESS = "wDRT_Wireless"


@dataclass(frozen=True)
class DeviceSpec:
    """
    Specification for a DRT device type.

    Attributes:
        vid: USB Vendor ID
        pid: USB Product ID
        name: Human-readable device name
        baudrate: Serial communication baudrate
    """
    vid: int
    pid: int
    name: str
    baudrate: int = 921600

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
DEVICE_REGISTRY: Dict[DRTDeviceType, DeviceSpec] = {
    DRTDeviceType.SDRT: DeviceSpec(
        vid=0x239A,
        pid=0x801E,
        name='sDRT',
        baudrate=9600
    ),
    DRTDeviceType.WDRT_USB: DeviceSpec(
        vid=0xF056,
        pid=0x0457,
        name='wDRT',
        baudrate=921600
    ),
}

# XBee dongle specification (used for wireless wDRT)
XBEE_DONGLE = DeviceSpec(
    vid=0x0403,
    pid=0x6015,
    name='XBee',
    baudrate=921600
)


def identify_device_type(port_info) -> Optional[DRTDeviceType]:
    """
    Identify the DRT device type from a serial port.

    Args:
        port_info: A serial.tools.list_ports.ListPortInfo object

    Returns:
        The matching DRTDeviceType, or None if not a known DRT device
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


def get_device_spec(device_type: DRTDeviceType) -> Optional[DeviceSpec]:
    """
    Get the device specification for a given device type.

    Args:
        device_type: The DRT device type

    Returns:
        The DeviceSpec for USB-based types, None for wireless
    """
    return DEVICE_REGISTRY.get(device_type)
