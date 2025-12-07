"""
Unified device registry for all supported USB and wireless devices.

This replaces the separate registries in:
- rpi_logger/modules/VOG/vog_core/device_types.py
- rpi_logger/modules/DRT/drt_core/device_types.py
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Set, Tuple
import re


class InterfaceType(Enum):
    """Physical connection interface types."""
    USB = "USB"              # USB-connected devices (serial, audio, cameras)
    XBEE = "XBee"            # XBee wireless (via USB dongle)
    NETWORK = "Network"      # Network/mDNS discovered devices
    CSI = "CSI"              # Raspberry Pi Camera Serial Interface
    INTERNAL = "Internal"    # Software-only (no hardware)
    UART = "UART"            # Built-in serial ports (Pi GPIO UART)


class DeviceFamily(Enum):
    """Device family classification (what type of device)."""
    VOG = "VOG"
    DRT = "DRT"
    EYE_TRACKER = "EyeTracker"
    AUDIO = "Audio"          # Microphones
    CAMERA = "Camera"        # USB cameras and Pi CSI cameras
    INTERNAL = "Internal"    # Software-only modules (no hardware)
    GPS = "GPS"              # GPS receivers


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

    # Eye Tracker devices (network-based)
    PUPIL_LABS_NEON = "Pupil_Labs_Neon"

    # Audio devices (discovered via sounddevice)
    USB_MICROPHONE = "USB_Microphone"

    # Internal/virtual devices (always available, no hardware)
    NOTES = "Notes"

    # Camera devices (discovered via /dev/video* or Picamera2)
    USB_CAMERA = "USB_Camera"
    PI_CAMERA = "Pi_Camera"

    # GPS devices (discovered via UART path check)
    BERRY_GPS = "BerryGPS"


@dataclass(frozen=True)
class DeviceSpec:
    """Specification for a device type."""
    device_type: DeviceType
    family: DeviceFamily
    interface_type: InterfaceType  # Which interface this device uses
    vid: Optional[int]          # USB Vendor ID (None for wireless/network)
    pid: Optional[int]          # USB Product ID (None for wireless/network)
    baudrate: int               # Serial baudrate (0 for network devices)
    display_name: str
    module_id: str              # Which module handles this device
    is_coordinator: bool = False
    is_network: bool = False    # True for network-discovered devices
    is_internal: bool = False   # True for software-only "devices" (always available)
    fixed_path: Optional[str] = None  # For UART devices: fixed device path (e.g., /dev/serial0)


# Unified XBee baudrate - use higher rate to support wDRT
XBEE_BAUDRATE = 921600


# Complete registry of all supported devices
DEVICE_REGISTRY: Dict[DeviceType, DeviceSpec] = {
    # VOG devices
    DeviceType.SVOG: DeviceSpec(
        device_type=DeviceType.SVOG,
        family=DeviceFamily.VOG,
        interface_type=InterfaceType.USB,
        vid=0x16C0,
        pid=0x0483,
        baudrate=115200,
        display_name="VOG",
        module_id="Vog",
    ),
    DeviceType.WVOG_USB: DeviceSpec(
        device_type=DeviceType.WVOG_USB,
        family=DeviceFamily.VOG,
        interface_type=InterfaceType.USB,
        vid=0xF057,
        pid=0x08AE,
        baudrate=57600,
        display_name="VOG",
        module_id="Vog",
    ),
    DeviceType.WVOG_WIRELESS: DeviceSpec(
        device_type=DeviceType.WVOG_WIRELESS,
        family=DeviceFamily.VOG,
        interface_type=InterfaceType.XBEE,
        vid=None,
        pid=None,
        baudrate=57600,
        display_name="VOG",
        module_id="Vog",
    ),

    # DRT devices
    DeviceType.SDRT: DeviceSpec(
        device_type=DeviceType.SDRT,
        family=DeviceFamily.DRT,
        interface_type=InterfaceType.USB,
        vid=0x239A,
        pid=0x801E,
        baudrate=9600,
        display_name="DRT",
        module_id="Drt",
    ),
    DeviceType.WDRT_USB: DeviceSpec(
        device_type=DeviceType.WDRT_USB,
        family=DeviceFamily.DRT,
        interface_type=InterfaceType.USB,
        vid=0xF056,
        pid=0x0457,
        baudrate=921600,
        display_name="DRT",
        module_id="Drt",
    ),
    DeviceType.WDRT_WIRELESS: DeviceSpec(
        device_type=DeviceType.WDRT_WIRELESS,
        family=DeviceFamily.DRT,
        interface_type=InterfaceType.XBEE,
        vid=None,
        pid=None,
        baudrate=921600,
        display_name="DRT",
        module_id="Drt",
    ),

    # XBee coordinator (same VID/PID, used for both VOG and DRT wireless)
    DeviceType.XBEE_COORDINATOR: DeviceSpec(
        device_type=DeviceType.XBEE_COORDINATOR,
        family=DeviceFamily.VOG,  # Arbitrary, handles both families
        interface_type=InterfaceType.USB,  # Coordinator itself is USB
        vid=0x0403,
        pid=0x6015,
        baudrate=XBEE_BAUDRATE,
        display_name="XBee Coordinator",
        module_id="",  # No specific module - routes to both
        is_coordinator=True,
    ),

    # Eye Tracker (network-based, discovered via mDNS)
    DeviceType.PUPIL_LABS_NEON: DeviceSpec(
        device_type=DeviceType.PUPIL_LABS_NEON,
        family=DeviceFamily.EYE_TRACKER,
        interface_type=InterfaceType.NETWORK,
        vid=None,
        pid=None,
        baudrate=0,  # Not applicable for network devices
        display_name="Eye Tracker",
        module_id="EyeTracker",
        is_network=True,
    ),

    # Audio devices (USB microphones, discovered via sounddevice)
    DeviceType.USB_MICROPHONE: DeviceSpec(
        device_type=DeviceType.USB_MICROPHONE,
        family=DeviceFamily.AUDIO,
        interface_type=InterfaceType.USB,  # USB interface, Audio device family
        vid=None,  # Audio uses sounddevice, not USB VID/PID
        pid=None,
        baudrate=0,  # Not applicable for audio devices
        display_name="Microphone",
        module_id="Audio",
    ),

    # Internal/virtual devices (always available, no hardware scanning)
    DeviceType.NOTES: DeviceSpec(
        device_type=DeviceType.NOTES,
        family=DeviceFamily.INTERNAL,
        interface_type=InterfaceType.INTERNAL,
        vid=None,
        pid=None,
        baudrate=0,
        display_name="Notes",
        module_id="Notes",
        is_internal=True,
    ),

    # USB Camera devices (discovered via /dev/video* enumeration)
    DeviceType.USB_CAMERA: DeviceSpec(
        device_type=DeviceType.USB_CAMERA,
        family=DeviceFamily.CAMERA,
        interface_type=InterfaceType.USB,  # USB interface, Camera device family
        vid=None,  # Cameras discovered via /dev/video* enumeration, not VID/PID
        pid=None,
        baudrate=0,  # Not a serial device
        display_name="USB Camera",
        module_id="Cameras",
    ),

    # Pi CSI Camera devices (discovered via Picamera2)
    DeviceType.PI_CAMERA: DeviceSpec(
        device_type=DeviceType.PI_CAMERA,
        family=DeviceFamily.CAMERA,
        interface_type=InterfaceType.CSI,  # CSI interface, Camera device family
        vid=None,  # Discovered via Picamera2.global_camera_info()
        pid=None,
        baudrate=0,  # Not a serial device
        display_name="Pi Camera",
        module_id="Cameras",
    ),

    # GPS devices (UART, discovered via fixed path check)
    DeviceType.BERRY_GPS: DeviceSpec(
        device_type=DeviceType.BERRY_GPS,
        family=DeviceFamily.GPS,
        interface_type=InterfaceType.UART,
        vid=None,
        pid=None,
        baudrate=9600,
        display_name="GPS",
        module_id="Gps",
        fixed_path="/dev/serial0",
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


# Type alias for connection key: (InterfaceType, DeviceFamily)
ConnectionKey = Tuple[InterfaceType, DeviceFamily]


def get_available_connections() -> Dict[InterfaceType, Set[DeviceFamily]]:
    """
    Get all available interface+device family combinations.

    Returns:
        Dict mapping InterfaceType to set of DeviceFamily that use that interface.
        Excludes coordinators (they're infrastructure, not user-selectable).
    """
    connections: Dict[InterfaceType, Set[DeviceFamily]] = {}

    for spec in DEVICE_REGISTRY.values():
        # Skip coordinators - they're infrastructure
        if spec.is_coordinator:
            continue

        interface = spec.interface_type
        family = spec.family

        if interface not in connections:
            connections[interface] = set()
        connections[interface].add(family)

    return connections


def get_devices_for_connection(interface: InterfaceType, family: DeviceFamily) -> list[DeviceSpec]:
    """
    Get all device specs for a given interface+family combination.

    Args:
        interface: The interface type (USB, Wireless, etc.)
        family: The device family (VOG, DRT, etc.)

    Returns:
        List of DeviceSpec that match both interface and family
    """
    return [
        spec for spec in DEVICE_REGISTRY.values()
        if spec.interface_type == interface and spec.family == family and not spec.is_coordinator
    ]


def get_connections_by_family() -> Dict[DeviceFamily, Set[InterfaceType]]:
    """
    Get all available device family + interface combinations, grouped by family.

    Returns:
        Dict mapping DeviceFamily to set of InterfaceType that support that family.
        Excludes coordinators (they're infrastructure, not user-selectable).
    """
    connections: Dict[DeviceFamily, Set[InterfaceType]] = {}

    for spec in DEVICE_REGISTRY.values():
        if spec.is_coordinator:
            continue

        family = spec.family
        interface = spec.interface_type

        if family not in connections:
            connections[family] = set()
        connections[family].add(interface)

    return connections


def get_connection_display_name(family: DeviceFamily) -> str:
    """Get human-readable display name for a device family."""
    display_names = {
        DeviceFamily.VOG: "VOG",
        DeviceFamily.DRT: "DRT",
        DeviceFamily.EYE_TRACKER: "Eye Tracker",
        DeviceFamily.AUDIO: "Microphone",
        DeviceFamily.INTERNAL: "Notes",
        DeviceFamily.CAMERA: "Camera",
        DeviceFamily.GPS: "GPS",
    }
    return display_names.get(family, family.value)


def get_interface_display_name(interface: InterfaceType) -> str:
    """Get human-readable display name for an interface type."""
    display_names = {
        InterfaceType.USB: "USB",
        InterfaceType.XBEE: "XBee",
        InterfaceType.NETWORK: "Network",
        InterfaceType.CSI: "CSI",
        InterfaceType.INTERNAL: "Internal",
        InterfaceType.UART: "UART",
    }
    return display_names.get(interface, interface.value)


def get_uart_device_specs() -> list[DeviceSpec]:
    """Get all device specs that use UART interface with fixed paths."""
    return [
        spec for spec in DEVICE_REGISTRY.values()
        if spec.interface_type == InterfaceType.UART and spec.fixed_path
    ]
