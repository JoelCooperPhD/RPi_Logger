"""DRT device type enum for sDRT, wDRT USB, and wDRT Wireless."""

from enum import Enum


class DRTDeviceType(Enum):
    SDRT = "DRT"
    WDRT_USB = "wDRT_USB"
    WDRT_WIRELESS = "wDRT_Wireless"
