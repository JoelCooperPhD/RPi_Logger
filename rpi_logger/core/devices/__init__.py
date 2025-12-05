"""
Core device management for RS Logger.

This package provides centralized device discovery and connection management,
replacing the per-module scanning that was previously in VOG and DRT modules.
"""

from .device_registry import (
    DeviceFamily,
    DeviceType,
    DeviceSpec,
    DEVICE_REGISTRY,
    XBEE_BAUDRATE,
    identify_usb_device,
    get_spec,
    get_module_for_device,
    parse_wireless_node_id,
    extract_device_number,
)

from .usb_scanner import (
    USBScanner,
    DiscoveredUSBDevice,
)

from .xbee_manager import (
    XBeeManager,
    XBeeManagerState,
    WirelessDevice,
    XBEE_AVAILABLE,
    is_xbee_dongle,
)

from .connection_manager import (
    DeviceConnectionManager,
    ConnectionState,
    DeviceInfo,
    XBeeDongleInfo,
)

__all__ = [
    # Device Registry
    "DeviceFamily",
    "DeviceType",
    "DeviceSpec",
    "DEVICE_REGISTRY",
    "XBEE_BAUDRATE",
    "identify_usb_device",
    "get_spec",
    "get_module_for_device",
    "parse_wireless_node_id",
    "extract_device_number",
    # USB Scanner
    "USBScanner",
    "DiscoveredUSBDevice",
    # XBee Manager
    "XBeeManager",
    "XBeeManagerState",
    "WirelessDevice",
    "XBEE_AVAILABLE",
    "is_xbee_dongle",
    # Connection Manager
    "DeviceConnectionManager",
    "ConnectionState",
    "DeviceInfo",
    "XBeeDongleInfo",
]
