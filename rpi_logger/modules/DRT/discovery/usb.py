"""
DRT USB device identification.

Matches USB devices by VID/PID to determine if they are DRT devices.
"""

from typing import Optional

from rpi_logger.core.devices.discovery_protocol import DeviceMatch
from rpi_logger.core.devices.types import InterfaceType
from .spec import DISCOVERY_SPEC


def identify_drt_device(vid: int, pid: int) -> Optional[DeviceMatch]:
    """
    Check if VID/PID matches a DRT device.

    Args:
        vid: USB Vendor ID
        pid: USB Product ID

    Returns:
        DeviceMatch if recognized, None otherwise
    """
    for spec in DISCOVERY_SPEC.usb_devices:
        if spec.vid == vid and spec.pid == pid:
            return DeviceMatch(
                module_id=DISCOVERY_SPEC.module_id,
                device_name=spec.name,
                family=DISCOVERY_SPEC.family,
                interface_type=InterfaceType.USB,
                baudrate=spec.baudrate,
            )
    return None
