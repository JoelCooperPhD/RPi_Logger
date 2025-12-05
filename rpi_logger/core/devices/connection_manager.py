"""
Central device connection manager.

Coordinates USB scanning, XBee management, and device-to-module routing.
Provides unified interface for the UI to manage device connections.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, Set, Awaitable
from enum import Enum

from rpi_logger.core.logging_utils import get_module_logger
from .device_registry import DeviceType, DeviceFamily, get_spec, get_module_for_device
from .usb_scanner import USBScanner, DiscoveredUSBDevice
from .xbee_manager import XBeeManager, WirelessDevice, XBEE_AVAILABLE

logger = get_module_logger("DeviceConnectionManager")


class ConnectionState(Enum):
    """Device connection state from UI perspective."""
    DISCOVERED = "discovered"    # Found but not connected to module
    CONNECTING = "connecting"    # Connection in progress
    CONNECTED = "connected"      # Actively connected to module
    ERROR = "error"              # Connection failed


@dataclass
class DeviceInfo:
    """Device information for UI display and module routing."""
    device_id: str               # Unique ID (port for USB, node_id for wireless)
    device_type: DeviceType
    family: DeviceFamily
    display_name: str
    port: Optional[str]          # USB port, or None for wireless
    baudrate: int
    module_id: str               # Which module handles this device
    state: ConnectionState = ConnectionState.DISCOVERED
    battery_percent: Optional[int] = None
    error_message: Optional[str] = None
    parent_id: Optional[str] = None  # For wireless: the dongle port
    is_wireless: bool = False


@dataclass
class XBeeDongleInfo:
    """XBee dongle information for UI."""
    port: str
    state: ConnectionState = ConnectionState.DISCOVERED
    child_devices: Dict[str, DeviceInfo] = field(default_factory=dict)


# Callback type for notifying UI of changes
DevicesChangedCallback = Callable[[], None]
DeviceConnectedCallback = Callable[[DeviceInfo], Awaitable[None]]
DeviceDisconnectedCallback = Callable[[str], Awaitable[None]]


class DeviceConnectionManager:
    """
    Central manager for all device connections.

    Coordinates USB scanning, XBee management, and device-to-module routing.
    """

    def __init__(self):
        # Initialize scanners
        self._usb_scanner = USBScanner(
            on_device_found=self._on_usb_device_found,
            on_device_lost=self._on_usb_device_lost,
        )

        self._xbee_manager: Optional[XBeeManager] = None
        if XBEE_AVAILABLE:
            self._xbee_manager = XBeeManager()
            self._xbee_manager.on_dongle_connected = self._on_xbee_dongle_connected
            self._xbee_manager.on_dongle_disconnected = self._on_xbee_dongle_disconnected
            self._xbee_manager.on_device_discovered = self._on_wireless_device_discovered
            self._xbee_manager.on_device_lost = self._on_wireless_device_lost

        # Device tracking
        self._usb_devices: Dict[str, DeviceInfo] = {}
        self._xbee_dongles: Dict[str, XBeeDongleInfo] = {}
        self._connected_devices: Set[str] = set()  # device_ids that are connected

        # Callbacks
        self._on_devices_changed: Optional[DevicesChangedCallback] = None
        self._on_device_connected: Optional[DeviceConnectedCallback] = None
        self._on_device_disconnected: Optional[DeviceDisconnectedCallback] = None

        # State
        self._scanning_enabled = False

    # =========================================================================
    # Callback Registration
    # =========================================================================

    def set_devices_changed_callback(self, callback: DevicesChangedCallback) -> None:
        """Set callback for when device list changes (for UI updates)."""
        self._on_devices_changed = callback

    def set_device_connected_callback(self, callback: DeviceConnectedCallback) -> None:
        """Set callback for when a device is connected to a module."""
        self._on_device_connected = callback

    def set_device_disconnected_callback(self, callback: DeviceDisconnectedCallback) -> None:
        """Set callback for when a device is disconnected from a module."""
        self._on_device_disconnected = callback

    # =========================================================================
    # Scanning Control
    # =========================================================================

    async def start_scanning(self) -> None:
        """Start USB and XBee device scanning."""
        if self._scanning_enabled:
            return

        self._scanning_enabled = True
        await self._usb_scanner.start()

        if self._xbee_manager:
            await self._xbee_manager.start()

        logger.info("Device scanning enabled")

    async def stop_scanning(self) -> None:
        """Stop USB and XBee device scanning."""
        if not self._scanning_enabled:
            return

        self._scanning_enabled = False
        await self._usb_scanner.stop()

        if self._xbee_manager:
            await self._xbee_manager.stop()

        # Clear device tracking but notify about disconnections first
        for device_id in list(self._connected_devices):
            await self._disconnect_device_internal(device_id)

        self._usb_devices.clear()
        self._xbee_dongles.clear()
        self._notify_changed()

        logger.info("Device scanning disabled")

    @property
    def is_scanning(self) -> bool:
        """Check if scanning is enabled."""
        return self._scanning_enabled

    async def force_scan(self) -> None:
        """Force an immediate device scan."""
        if self._scanning_enabled:
            await self._usb_scanner.force_scan()
            if self._xbee_manager and self._xbee_manager.is_connected:
                await self._xbee_manager.trigger_rediscovery()

    # =========================================================================
    # Device Access
    # =========================================================================

    def get_all_devices(self) -> list[DeviceInfo]:
        """Get all discovered USB devices (excluding dongles)."""
        return list(self._usb_devices.values())

    def get_xbee_dongles(self) -> list[XBeeDongleInfo]:
        """Get all XBee dongles with their child devices."""
        return list(self._xbee_dongles.values())

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Get a specific device by ID."""
        return self._find_device(device_id)

    def get_devices_for_module(self, module_id: str) -> list[DeviceInfo]:
        """Get all devices that belong to a specific module."""
        devices = []

        # USB devices
        for device in self._usb_devices.values():
            if device.module_id == module_id:
                devices.append(device)

        # Wireless devices
        for dongle in self._xbee_dongles.values():
            for device in dongle.child_devices.values():
                if device.module_id == module_id:
                    devices.append(device)

        return devices

    def get_connected_devices(self) -> list[DeviceInfo]:
        """Get all devices that are currently connected to modules."""
        devices = []
        for device_id in self._connected_devices:
            device = self._find_device(device_id)
            if device:
                devices.append(device)
        return devices

    def get_connected_devices_for_module(self, module_id: str) -> list[DeviceInfo]:
        """Get connected devices for a specific module."""
        return [
            d for d in self.get_connected_devices()
            if d.module_id == module_id
        ]

    def is_device_connected(self, device_id: str) -> bool:
        """Check if device is connected to a module."""
        return device_id in self._connected_devices

    # =========================================================================
    # Connection Control
    # =========================================================================

    async def connect_device(self, device_id: str) -> bool:
        """
        Connect a device (mark for module assignment).

        Args:
            device_id: The device to connect

        Returns:
            True if connection initiated successfully
        """
        device = self._find_device(device_id)
        if not device:
            logger.error(f"Device not found: {device_id}")
            return False

        if device_id in self._connected_devices:
            logger.warning(f"Device already connected: {device_id}")
            return True

        device.state = ConnectionState.CONNECTING
        self._notify_changed()

        # Mark as connected
        device.state = ConnectionState.CONNECTED
        self._connected_devices.add(device_id)
        self._notify_changed()

        logger.info(f"Device connected: {device_id} ({device.device_type.value})")

        # Notify callback
        if self._on_device_connected:
            await self._on_device_connected(device)

        return True

    async def disconnect_device(self, device_id: str) -> None:
        """Disconnect a device from its module."""
        await self._disconnect_device_internal(device_id)
        self._notify_changed()

    async def _disconnect_device_internal(self, device_id: str) -> None:
        """Internal disconnect without UI notification."""
        device = self._find_device(device_id)
        if device and device_id in self._connected_devices:
            device.state = ConnectionState.DISCOVERED
            self._connected_devices.discard(device_id)

            logger.info(f"Device disconnected: {device_id}")

            if self._on_device_disconnected:
                await self._on_device_disconnected(device_id)

    async def disconnect_all_for_module(self, module_id: str) -> None:
        """Disconnect all devices for a specific module."""
        devices = self.get_connected_devices_for_module(module_id)
        for device in devices:
            await self._disconnect_device_internal(device.device_id)
        self._notify_changed()

    # =========================================================================
    # USB Scanner Callbacks
    # =========================================================================

    async def _on_usb_device_found(self, usb_device: DiscoveredUSBDevice) -> None:
        """Handle new USB device discovery."""
        # Check if XBee dongle
        if usb_device.device_type == DeviceType.XBEE_COORDINATOR:
            self._xbee_dongles[usb_device.port] = XBeeDongleInfo(port=usb_device.port)
            logger.info(f"XBee dongle discovered: {usb_device.port}")
        else:
            spec = usb_device.spec
            device_info = DeviceInfo(
                device_id=usb_device.port,
                device_type=usb_device.device_type,
                family=spec.family,
                display_name=f"{spec.display_name} on {usb_device.port}",
                port=usb_device.port,
                baudrate=spec.baudrate,
                module_id=spec.module_id,
                is_wireless=False,
            )
            self._usb_devices[usb_device.port] = device_info
            logger.info(f"USB device discovered: {device_info.display_name}")

        self._notify_changed()

    async def _on_usb_device_lost(self, port: str) -> None:
        """Handle USB device disconnection."""
        # Check if it was a connected device
        if port in self._connected_devices:
            await self._disconnect_device_internal(port)

        device = self._usb_devices.pop(port, None)
        dongle = self._xbee_dongles.pop(port, None)

        if device:
            logger.info(f"USB device lost: {device.display_name}")

        if dongle:
            logger.info(f"XBee dongle lost: {port}")
            # Child devices are handled by XBee manager callbacks

        self._notify_changed()

    # =========================================================================
    # XBee Manager Callbacks
    # =========================================================================

    async def _on_xbee_dongle_connected(self, port: str) -> None:
        """Handle XBee dongle connection."""
        if port in self._xbee_dongles:
            self._xbee_dongles[port].state = ConnectionState.CONNECTED
            logger.info(f"XBee dongle connected: {port}")
            self._notify_changed()

    async def _on_xbee_dongle_disconnected(self) -> None:
        """Handle XBee dongle disconnection."""
        for dongle in self._xbee_dongles.values():
            # Disconnect all child devices
            for device_id in list(dongle.child_devices.keys()):
                if device_id in self._connected_devices:
                    await self._disconnect_device_internal(device_id)
            dongle.child_devices.clear()
            dongle.state = ConnectionState.DISCOVERED

        self._notify_changed()

    async def _on_wireless_device_discovered(
        self,
        wireless_device: WirelessDevice,
        remote_xbee
    ) -> None:
        """Handle wireless device discovery."""
        dongle_port = self._xbee_manager.coordinator_port if self._xbee_manager else None
        if not dongle_port or dongle_port not in self._xbee_dongles:
            return

        spec = get_spec(wireless_device.device_type)
        dongle = self._xbee_dongles[dongle_port]

        device_info = DeviceInfo(
            device_id=wireless_device.node_id,
            device_type=wireless_device.device_type,
            family=wireless_device.family,
            display_name=wireless_device.node_id,
            port=dongle_port,  # Use dongle port for wireless devices
            baudrate=spec.baudrate,
            module_id=spec.module_id,
            battery_percent=wireless_device.battery_percent,
            parent_id=dongle_port,
            is_wireless=True,
        )

        dongle.child_devices[wireless_device.node_id] = device_info
        logger.info(f"Wireless device discovered: {wireless_device.node_id}")
        self._notify_changed()

    async def _on_wireless_device_lost(self, node_id: str) -> None:
        """Handle wireless device loss."""
        # Disconnect if connected
        if node_id in self._connected_devices:
            await self._disconnect_device_internal(node_id)

        # Remove from dongle
        for dongle in self._xbee_dongles.values():
            if node_id in dongle.child_devices:
                del dongle.child_devices[node_id]
                logger.info(f"Wireless device lost: {node_id}")
                break

        self._notify_changed()

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _find_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Find device by ID (checks USB devices and wireless devices)."""
        # Check USB devices
        if device_id in self._usb_devices:
            return self._usb_devices[device_id]

        # Check wireless devices under dongles
        for dongle in self._xbee_dongles.values():
            if device_id in dongle.child_devices:
                return dongle.child_devices[device_id]

        return None

    def _notify_changed(self) -> None:
        """Notify UI of device list change."""
        if self._on_devices_changed:
            self._on_devices_changed()

    # =========================================================================
    # XBee Access (for modules that need raw XBee communication)
    # =========================================================================

    def get_xbee_manager(self) -> Optional[XBeeManager]:
        """Get the XBee manager (for modules that need it)."""
        return self._xbee_manager

    async def send_to_wireless_device(self, node_id: str, data: bytes) -> bool:
        """Send data to a wireless device."""
        if self._xbee_manager:
            return await self._xbee_manager.send_to_device(node_id, data)
        return False
