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
