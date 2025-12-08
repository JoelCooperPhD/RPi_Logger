"""VOG Device Types.

Defines device type enums and conversion utilities.
Device discovery is handled by the main logger - this module receives device assignments.
"""

from enum import Enum
from typing import Optional


class VOGDeviceType(Enum):
    """Supported VOG device types."""
    SVOG = "sVOG"
    WVOG_USB = "wVOG_USB"
    WVOG_WIRELESS = "wVOG_Wireless"


def device_type_from_string(type_str: str) -> Optional[VOGDeviceType]:
    """Convert a string device type to VOGDeviceType enum.

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
