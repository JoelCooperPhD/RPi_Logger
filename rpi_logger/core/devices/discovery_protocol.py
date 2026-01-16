"""
Module discovery protocol definitions.

This module defines the protocol and data classes that modules use to
declare their device discovery capabilities. Core loads these specs
from modules and builds runtime discovery handlers.

Two discovery models:
1. Device-specific (DRT, VOG, GPS): Module provides VID/PIDs, XBee patterns
2. Category-based (Cameras, Audio, EyeTracker): Module provides custom scanner
"""

from dataclasses import dataclass, field
from typing import Protocol, Optional, Callable, Awaitable, Any, runtime_checkable

from .types import DeviceFamily, InterfaceType


@dataclass(frozen=True)
class USBDeviceSpec:
    """USB device identification for serial devices (DRT, VOG)."""
    vid: int
    pid: int
    baudrate: int = 0
    name: str = ""


@dataclass(frozen=True)
class XBeePattern:
    """XBee node ID pattern for wireless device matching."""
    prefix: str          # "wDRT", "wVOG"
    baudrate: int


@dataclass
class ModuleDiscoverySpec:
    """
    Specification for how a module discovers its devices.

    Each module provides one of these in their discovery package.
    Core loads these specs and builds the device discovery system.
    """
    module_id: str
    display_name: str
    family: DeviceFamily
    interfaces: list[InterfaceType]

    # Device-specific discovery (module provides VID/PIDs and patterns)
    usb_devices: list[USBDeviceSpec] = field(default_factory=list)
    xbee_patterns: list[XBeePattern] = field(default_factory=list)
    uart_path: Optional[str] = None

    # Category discovery (module provides custom scanner)
    has_custom_scanner: bool = False

    # Module behavior
    multi_instance: bool = False
    is_internal: bool = False
    platforms: list[str] = field(default_factory=lambda: ["*"])

    # Device ID handling for modules with special device ID formats
    device_id_prefix: Optional[str] = None  # e.g., "picam:" for CSI cameras
    extra_cli_args: dict[str, str] = field(default_factory=dict)  # e.g., {"camera_index": "--camera-index"}


@dataclass
class DeviceMatch:
    """Result of a successful device match from module discovery."""
    module_id: str
    device_name: str
    family: DeviceFamily
    interface_type: InterfaceType
    baudrate: int = 0
    device_number: Optional[int] = None
    extra_data: dict = field(default_factory=dict)


# Type aliases for discovery callbacks
DeviceFoundCallback = Callable[[Any], Awaitable[None]]
DeviceLostCallback = Callable[[str], Awaitable[None]]


@runtime_checkable
class ScannerProtocol(Protocol):
    """Protocol for custom scanners provided by modules."""

    async def start(self) -> None:
        """Start the scanner."""
        ...

    async def stop(self) -> None:
        """Stop the scanner."""
        ...

    async def force_scan(self) -> None:
        """Force an immediate scan."""
        ...


@runtime_checkable
class ModuleDiscoveryProtocol(Protocol):
    """
    Protocol that module discovery packages must implement.

    Modules can implement either:
    1. Device-specific matching (identify_usb_device, parse_xbee_node)
    2. Custom scanning (create_scanner)
    3. Both
    """

    spec: ModuleDiscoverySpec

    def identify_usb_device(self, vid: int, pid: int) -> Optional[DeviceMatch]:
        """Check if VID/PID matches this module's devices."""
        ...

    def parse_xbee_node(self, node_id: str) -> Optional[DeviceMatch]:
        """Parse XBee node ID for this module's devices."""
        ...

    def create_scanner(
        self,
        on_found: DeviceFoundCallback,
        on_lost: DeviceLostCallback,
    ) -> ScannerProtocol:
        """Create a custom scanner for category-based discovery."""
        ...


class BaseModuleDiscovery:
    """
    Base class for module discovery implementations.

    Provides default implementations that return None/raise NotImplementedError.
    Modules extend this and override what they need.
    """

    spec: ModuleDiscoverySpec

    def identify_usb_device(self, vid: int, pid: int) -> Optional[DeviceMatch]:
        """Check if VID/PID matches this module's devices."""
        return None

    def parse_xbee_node(self, node_id: str) -> Optional[DeviceMatch]:
        """Parse XBee node ID for this module's devices."""
        return None

    def create_scanner(
        self,
        on_found: DeviceFoundCallback,
        on_lost: DeviceLostCallback,
    ) -> ScannerProtocol:
        """Create a custom scanner for category-based discovery."""
        raise NotImplementedError(
            f"Module {self.spec.module_id} has has_custom_scanner=True "
            "but doesn't implement create_scanner()"
        )
