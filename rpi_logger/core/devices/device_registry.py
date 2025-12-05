"""
Unified device registry for all supported USB and wireless devices.

This replaces the separate registries in:
- rpi_logger/modules/VOG/vog_core/device_types.py
- rpi_logger/modules/DRT/drt_core/device_types.py
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict
import re


class DeviceFamily(Enum):
    """Top-level device family classification."""
    VOG = "VOG"
    DRT = "DRT"


class DeviceType(Enum):
    """All supported device types across all modules."""
    # VOG devices
    SVOG = "sVOG"
    WVOG_USB = "wVOG_USB"
    WVOG_WIRELESS = "wVOG_Wireless"

    # DRT devices
    SDRT = "sDRT"
    WDRT_USB = "wDRT_USB"
    WDRT_WIRELESS = "wDRT_Wireless"

    # Coordinator dongles
    XBEE_COORDINATOR = "XBee_Coordinator"


@dataclass(frozen=True)
class DeviceSpec:
    """Specification for a device type."""
    device_type: DeviceType
    family: DeviceFamily
    vid: Optional[int]          # USB Vendor ID (None for wireless)
    pid: Optional[int]          # USB Product ID (None for wireless)
    baudrate: int
    display_name: str
    module_id: str              # Which module handles this device ("vog" or "drt")
    is_coordinator: bool = False


# Unified XBee baudrate - use higher rate to support wDRT
XBEE_BAUDRATE = 921600


# Complete registry of all supported devices
DEVICE_REGISTRY: Dict[DeviceType, DeviceSpec] = {
    # VOG devices
    DeviceType.SVOG: DeviceSpec(
        device_type=DeviceType.SVOG,
        family=DeviceFamily.VOG,
        vid=0x16C0,
        pid=0x0483,
        baudrate=115200,
        display_name="sVOG",
        module_id="Vog",
    ),
    DeviceType.WVOG_USB: DeviceSpec(
        device_type=DeviceType.WVOG_USB,
        family=DeviceFamily.VOG,
        vid=0xF057,
        pid=0x08AE,
        baudrate=57600,
        display_name="wVOG (USB)",
        module_id="Vog",
    ),
    DeviceType.WVOG_WIRELESS: DeviceSpec(
        device_type=DeviceType.WVOG_WIRELESS,
        family=DeviceFamily.VOG,
        vid=None,
        pid=None,
        baudrate=57600,
        display_name="wVOG (Wireless)",
        module_id="Vog",
    ),

    # DRT devices
    DeviceType.SDRT: DeviceSpec(
        device_type=DeviceType.SDRT,
        family=DeviceFamily.DRT,
        vid=0x239A,
        pid=0x801E,
        baudrate=9600,
        display_name="sDRT",
        module_id="Drt",
    ),
    DeviceType.WDRT_USB: DeviceSpec(
        device_type=DeviceType.WDRT_USB,
        family=DeviceFamily.DRT,
        vid=0xF056,
        pid=0x0457,
        baudrate=921600,
        display_name="wDRT (USB)",
        module_id="Drt",
    ),
    DeviceType.WDRT_WIRELESS: DeviceSpec(
        device_type=DeviceType.WDRT_WIRELESS,
        family=DeviceFamily.DRT,
        vid=None,
        pid=None,
        baudrate=921600,
        display_name="wDRT (Wireless)",
        module_id="Drt",
    ),

    # XBee coordinator (same VID/PID, used for both VOG and DRT wireless)
    DeviceType.XBEE_COORDINATOR: DeviceSpec(
        device_type=DeviceType.XBEE_COORDINATOR,
        family=DeviceFamily.VOG,  # Arbitrary, handles both families
        vid=0x0403,
        pid=0x6015,
        baudrate=XBEE_BAUDRATE,
        display_name="XBee Coordinator",
        module_id="",  # No specific module - routes to both
        is_coordinator=True,
    ),
}


def identify_usb_device(vid: int, pid: int) -> Optional[DeviceSpec]:
    """
    Identify a USB device by VID/PID.

    Args:
        vid: USB Vendor ID
        pid: USB Product ID

    Returns:
        DeviceSpec if recognized, None otherwise
    """
    for spec in DEVICE_REGISTRY.values():
        if spec.vid == vid and spec.pid == pid:
            return spec
    return None


def get_spec(device_type: DeviceType) -> DeviceSpec:
    """Get specification for a device type."""
    return DEVICE_REGISTRY[device_type]


def get_module_for_device(device_type: DeviceType) -> str:
    """
    Get the module ID that handles a device type.

    Args:
        device_type: The device type

    Returns:
        Module ID string ("vog" or "drt"), empty string for coordinators
    """
    return DEVICE_REGISTRY[device_type].module_id


def parse_wireless_node_id(node_id: str) -> Optional[DeviceType]:
    """
    Parse XBee node ID to determine device type.

    Expected formats:
    - "wVOG_XX" or "wVOG XX" -> DeviceType.WVOG_WIRELESS
    - "wDRT_XX" or "wDRT XX" -> DeviceType.WDRT_WIRELESS

    Args:
        node_id: The XBee node identifier string

    Returns:
        DeviceType if recognized, None otherwise
    """
    match = re.match(r'^([a-zA-Z]+)[_\s]*(\d+)$', node_id.strip())
    if not match:
        return None

    device_type_str = match.group(1).lower()

    if device_type_str == 'wvog':
        return DeviceType.WVOG_WIRELESS
    elif device_type_str == 'wdrt':
        return DeviceType.WDRT_WIRELESS

    return None


def extract_device_number(node_id: str) -> Optional[int]:
    """
    Extract the device number from a wireless node ID.

    Args:
        node_id: The XBee node identifier string (e.g., "wVOG_01")

    Returns:
        Device number as int, or None if not parseable
    """
    match = re.match(r'^[a-zA-Z]+[_\s]*(\d+)$', node_id.strip())
    if match:
        return int(match.group(1))
    return None
