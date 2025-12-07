"""
Device Events - Unified event types for all device scanners.

All scanners emit these event types, providing a uniform interface
for device discovery and removal regardless of the underlying
scanning mechanism (USB, XBee, Network, etc.).
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, Callable, Awaitable

from .device_registry import DeviceType, DeviceFamily, InterfaceType


@dataclass
class DeviceDiscoveredEvent:
    """
    Emitted when any scanner discovers a device.

    This is the uniform event type that all scanners emit when they
    find a new device. The DeviceLifecycleManager handles these events
    uniformly regardless of the source scanner.

    Attributes:
        device_id: Unique identifier for the device (port, node_id, etc.)
        device_type: The specific device type from DeviceType enum
        family: Device family classification (VOG, DRT, Camera, etc.)
        interface: Interface type (USB, XBee, Network, etc.)
        raw_name: Scanner-provided name (may be None for serial devices)
        port: Serial port path or None for non-serial devices
        baudrate: Baud rate for serial devices, 0 otherwise
        module_id: Module identifier for auto-connect matching
        metadata: Scanner-specific additional data
    """
    device_id: str
    device_type: DeviceType
    family: DeviceFamily
    interface: InterfaceType
    raw_name: str | None = None
    port: str | None = None
    baudrate: int = 0
    module_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceLostEvent:
    """
    Emitted when any scanner loses a device.

    This is the uniform event type that all scanners emit when a
    device is removed or becomes unavailable.

    Attributes:
        device_id: Unique identifier for the lost device
    """
    device_id: str


# Type alias for device events
DeviceEvent = DeviceDiscoveredEvent | DeviceLostEvent

# Type alias for event handlers
DeviceEventHandler = Callable[[DeviceEvent], Awaitable[None]]


class ScannerProtocol(Protocol):
    """
    Protocol that all device scanners must implement.

    This provides a uniform interface for starting/stopping scanners
    and receiving device events.
    """

    async def start(self) -> None:
        """Start the scanner."""
        ...

    async def stop(self) -> None:
        """Stop the scanner."""
        ...

    def set_event_handler(self, handler: DeviceEventHandler) -> None:
        """Set the handler for device events."""
        ...


# =========================================================================
# Event Builders - Helper functions for scanners to create events
# =========================================================================

def discovered_usb_device(
    port: str,
    device_type: DeviceType,
    family: DeviceFamily,
    baudrate: int,
    module_id: str,
    raw_name: str | None = None,
) -> DeviceDiscoveredEvent:
    """Create a discovery event for a USB device."""
    return DeviceDiscoveredEvent(
        device_id=port,
        device_type=device_type,
        family=family,
        interface=InterfaceType.USB,
        raw_name=raw_name,
        port=port,
        baudrate=baudrate,
        module_id=module_id,
    )


def discovered_wireless_device(
    node_id: str,
    device_type: DeviceType,
    family: DeviceFamily,
    dongle_port: str,
    baudrate: int,
    module_id: str,
    battery_percent: int | None = None,
) -> DeviceDiscoveredEvent:
    """Create a discovery event for a wireless (XBee) device."""
    return DeviceDiscoveredEvent(
        device_id=node_id,
        device_type=device_type,
        family=family,
        interface=InterfaceType.XBEE,
        raw_name=None,
        port=dongle_port,
        baudrate=baudrate,
        module_id=module_id,
        metadata={
            "is_wireless": True,
            "battery_percent": battery_percent,
            "parent_id": dongle_port,
        },
    )


def discovered_network_device(
    device_id: str,
    device_type: DeviceType,
    family: DeviceFamily,
    module_id: str,
    name: str,
    address: str,
    port: int,
) -> DeviceDiscoveredEvent:
    """Create a discovery event for a network device."""
    return DeviceDiscoveredEvent(
        device_id=device_id,
        device_type=device_type,
        family=family,
        interface=InterfaceType.NETWORK,
        raw_name=name,
        port=None,
        baudrate=0,
        module_id=module_id,
        metadata={
            "is_network": True,
            "network_address": address,
            "network_port": port,
        },
    )


def discovered_audio_device(
    device_id: str,
    device_type: DeviceType,
    module_id: str,
    name: str,
    card_index: int | None = None,
    device_index: int | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
) -> DeviceDiscoveredEvent:
    """Create a discovery event for an audio device."""
    return DeviceDiscoveredEvent(
        device_id=device_id,
        device_type=device_type,
        family=DeviceFamily.AUDIO,
        interface=InterfaceType.USB,
        raw_name=name,
        port=None,
        baudrate=0,
        module_id=module_id,
        metadata={
            "is_audio": True,
            "card_index": card_index,
            "device_index": device_index,
            "sample_rate": sample_rate,
            "channels": channels,
        },
    )


def discovered_internal_device(
    device_id: str,
    device_type: DeviceType,
    family: DeviceFamily,
    module_id: str,
    raw_name: str | None = None,
) -> DeviceDiscoveredEvent:
    """Create a discovery event for an internal (virtual) device."""
    return DeviceDiscoveredEvent(
        device_id=device_id,
        device_type=device_type,
        family=family,
        interface=InterfaceType.INTERNAL,
        raw_name=raw_name,
        port=None,
        baudrate=0,
        module_id=module_id,
        metadata={"is_internal": True},
    )


def discovered_camera_device(
    device_id: str,
    device_type: DeviceType,
    interface: InterfaceType,
    module_id: str,
    friendly_name: str,
    stable_id: str | None = None,
    dev_path: str | None = None,
    hw_model: str | None = None,
    location_hint: str | None = None,
) -> DeviceDiscoveredEvent:
    """Create a discovery event for a camera device (USB or CSI)."""
    return DeviceDiscoveredEvent(
        device_id=device_id,
        device_type=device_type,
        family=DeviceFamily.CAMERA,
        interface=interface,
        raw_name=friendly_name,
        port=None,
        baudrate=0,
        module_id=module_id,
        metadata={
            "is_camera": True,
            "camera_type": "usb" if interface == InterfaceType.USB else "picam",
            "camera_stable_id": stable_id,
            "camera_dev_path": dev_path,
            "camera_hw_model": hw_model,
            "camera_location": location_hint,
        },
    )


def discovered_uart_device(
    device_id: str,
    device_type: DeviceType,
    family: DeviceFamily,
    path: str,
    baudrate: int,
    module_id: str,
    raw_name: str | None = None,
) -> DeviceDiscoveredEvent:
    """Create a discovery event for a UART device."""
    return DeviceDiscoveredEvent(
        device_id=device_id,
        device_type=device_type,
        family=family,
        interface=InterfaceType.UART,
        raw_name=raw_name,
        port=path,
        baudrate=baudrate,
        module_id=module_id,
        metadata={
            "is_uart": True,
            "uart_path": path,
        },
    )


def device_lost(device_id: str) -> DeviceLostEvent:
    """Create a device lost event."""
    return DeviceLostEvent(device_id=device_id)
