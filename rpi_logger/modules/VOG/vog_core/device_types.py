"""VOG device type enums."""

from enum import Enum
from typing import Optional


class VOGDeviceType(Enum):
    """Supported VOG device types."""
    SVOG = "sVOG"
    WVOG_USB = "wVOG_USB"
    WVOG_WIRELESS = "wVOG_Wireless"
