"""
Core device management for RS Logger.

This package provides centralized device discovery and connection management,
replacing the per-module scanning that was previously in VOG and DRT modules.
"""

from .device_registry import (
    InterfaceType,
    DeviceFamily,
    DeviceType,
    DeviceSpec,
    ConnectionKey,
    DEVICE_REGISTRY,
    XBEE_BAUDRATE,
    identify_usb_device,
    get_spec,
    get_module_for_device,
    parse_wireless_node_id,
    extract_device_number,
    get_available_connections,
    get_connections_by_family,
    get_devices_for_connection,
    get_connection_display_name,
    get_interface_display_name,
    get_uart_device_specs,
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

from .network_scanner import (
    NetworkScanner,
    DiscoveredNetworkDevice,
    ZEROCONF_AVAILABLE,
)

from .audio_scanner import (
    AudioScanner,
    DiscoveredAudioDevice,
    SOUNDDEVICE_AVAILABLE,
)

from .usb_camera_scanner import (
    USBCameraScanner,
    DiscoveredUSBCamera,
    CV2_AVAILABLE,
)

from .csi_scanner import (
    CSIScanner,
    DiscoveredCSICamera,
    PICAMERA2_AVAILABLE,
)

from .uart_scanner import (
    UARTScanner,
    DiscoveredUARTDevice,
)

from .internal_scanner import (
    InternalDeviceScanner,
    DiscoveredInternalDevice,
)

# New architecture components
from .catalog import DeviceCatalog, FamilyMetadata, InterfaceMetadata
from .selection import DeviceSelectionModel, ConnectionState
from .lifecycle import DeviceLifecycleManager, DeviceInfo
from .events import (
    DeviceDiscoveredEvent,
    DeviceLostEvent,
    DeviceEvent,
    ScannerProtocol,
)
from .scanner_adapter import ScannerEventAdapter
from .device_system import DeviceSystem

__all__ = [
    # Device Registry
    "InterfaceType",
    "DeviceFamily",
    "DeviceType",
    "DeviceSpec",
    "ConnectionKey",
    "DEVICE_REGISTRY",
    "XBEE_BAUDRATE",
    "identify_usb_device",
    "get_spec",
    "get_module_for_device",
    "parse_wireless_node_id",
    "extract_device_number",
    "get_available_connections",
    "get_connections_by_family",
    "get_devices_for_connection",
    "get_connection_display_name",
    "get_interface_display_name",
    # USB Scanner
    "USBScanner",
    "DiscoveredUSBDevice",
    # XBee Manager
    "XBeeManager",
    "XBeeManagerState",
    "WirelessDevice",
    "XBEE_AVAILABLE",
    "is_xbee_dongle",
    # Network Scanner
    "NetworkScanner",
    "DiscoveredNetworkDevice",
    "ZEROCONF_AVAILABLE",
    # Audio Scanner
    "AudioScanner",
    "DiscoveredAudioDevice",
    "SOUNDDEVICE_AVAILABLE",
    # USB Camera Scanner
    "USBCameraScanner",
    "DiscoveredUSBCamera",
    "CV2_AVAILABLE",
    # CSI Scanner (Pi cameras)
    "CSIScanner",
    "DiscoveredCSICamera",
    "PICAMERA2_AVAILABLE",
    # UART Scanner (fixed path serial devices)
    "UARTScanner",
    "DiscoveredUARTDevice",
    "get_uart_device_specs",
    # Internal Scanner (virtual devices)
    "InternalDeviceScanner",
    "DiscoveredInternalDevice",
    # New Architecture
    "ConnectionState",
    "DeviceInfo",
    "DeviceCatalog",
    "FamilyMetadata",
    "InterfaceMetadata",
    "DeviceSelectionModel",
    "DeviceLifecycleManager",
    "DeviceDiscoveredEvent",
    "DeviceLostEvent",
    "DeviceEvent",
    "ScannerProtocol",
    "ScannerEventAdapter",
    "DeviceSystem",
]
