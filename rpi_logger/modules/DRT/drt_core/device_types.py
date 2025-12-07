"""
DRT Device Types

Defines device types for all supported DRT variants:
- sDRT (USB only)
- wDRT (USB)
- wDRT (Wireless via XBee)

Device discovery is centralized in the main logger via usb_scanner.py
and xbee_manager.py. This module only defines the device type enum
used throughout the DRT module.
"""

from enum import Enum


class DRTDeviceType(Enum):
    """Enumeration of supported DRT device types."""
    SDRT = "sDRT"
    WDRT_USB = "wDRT_USB"
    WDRT_WIRELESS = "wDRT_Wireless"
