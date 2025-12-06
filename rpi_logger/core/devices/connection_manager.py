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
from .device_registry import (
    DeviceType, DeviceFamily, InterfaceType, ConnectionKey,
    get_spec, get_module_for_device, get_available_connections
)
from .usb_scanner import USBScanner, DiscoveredUSBDevice
from .xbee_manager import XBeeManager, WirelessDevice, XBEE_AVAILABLE
from .network_scanner import NetworkScanner, DiscoveredNetworkDevice, ZEROCONF_AVAILABLE
from .audio_scanner import AudioScanner, DiscoveredAudioDevice, SOUNDDEVICE_AVAILABLE
from .internal_scanner import InternalDeviceScanner, DiscoveredInternalDevice
from .usb_camera_scanner import USBCameraScanner, DiscoveredUSBCamera, CV2_AVAILABLE
from .csi_scanner import CSIScanner, DiscoveredCSICamera, PICAMERA2_AVAILABLE
from .uart_scanner import UARTScanner, DiscoveredUARTDevice
from .transports import XBeeTransport

logger = get_module_logger("DeviceConnectionManager")

# Callback type for saving/loading device connection state
DeviceConnectionStateCallback = Callable[[str, bool], Awaitable[None]]  # (module_id, connected)
LoadDeviceConnectionStateCallback = Callable[[str], Awaitable[bool]]  # (module_id) -> was_connected


class ConnectionState(Enum):
    """Device connection state from UI perspective."""
    DISCOVERED = "discovered"    # Found but not connected to module
    CONNECTING = "connecting"    # Connection in progress
    CONNECTED = "connected"      # Actively connected to module
    ERROR = "error"              # Connection failed


@dataclass
class DeviceInfo:
    """Device information for UI display and module routing."""
    device_id: str               # Unique ID (port for USB, node_id for wireless, hardware_id for network)
    device_type: DeviceType
    family: DeviceFamily
    interface_type: InterfaceType  # Which interface this device uses
    display_name: str
    port: Optional[str]          # USB port, or None for wireless/network
    baudrate: int
    module_id: str               # Which module handles this device
    state: ConnectionState = ConnectionState.DISCOVERED
    battery_percent: Optional[int] = None
    error_message: Optional[str] = None
    parent_id: Optional[str] = None  # For wireless: the dongle port
    is_wireless: bool = False
    # Network device fields
    is_network: bool = False
    network_address: Optional[str] = None  # IP address for network devices
    network_port: Optional[int] = None     # API port for network devices (e.g., 8080)
    # Audio device fields
    is_audio: bool = False
    sounddevice_index: Optional[int] = None  # Index for sounddevice
    audio_channels: Optional[int] = None     # Number of input channels
    audio_sample_rate: Optional[float] = None  # Sample rate
    # Internal device fields
    is_internal: bool = False  # True for software-only devices (always available)
    # Camera device fields
    is_camera: bool = False  # True for camera devices (USB or Pi)
    camera_type: Optional[str] = None  # "usb" or "picam"
    camera_stable_id: Optional[str] = None  # USB bus path or picam number
    camera_dev_path: Optional[str] = None  # /dev/video* path for USB cameras
    camera_hw_model: Optional[str] = None  # Hardware model
    camera_location: Optional[str] = None  # USB port or CSI connector
    # UART device fields
    is_uart: bool = False  # True for UART devices (fixed path serial)
    uart_path: Optional[str] = None  # The fixed device path (e.g., /dev/serial0)


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

        self._network_scanner: Optional[NetworkScanner] = None
        if ZEROCONF_AVAILABLE:
            self._network_scanner = NetworkScanner(
                on_device_found=self._on_network_device_found,
                on_device_lost=self._on_network_device_lost,
            )

        self._audio_scanner: Optional[AudioScanner] = None
        if SOUNDDEVICE_AVAILABLE:
            self._audio_scanner = AudioScanner(
                on_device_found=self._on_audio_device_found,
                on_device_lost=self._on_audio_device_lost,
            )

        # Internal device scanner (always available - no hardware dependency)
        self._internal_scanner = InternalDeviceScanner(
            on_device_found=self._on_internal_device_found,
            on_device_lost=self._on_internal_device_lost,
        )

        # USB Camera scanner (requires cv2)
        self._usb_camera_scanner: Optional[USBCameraScanner] = None
        if CV2_AVAILABLE:
            self._usb_camera_scanner = USBCameraScanner(
                on_device_found=self._on_usb_camera_found,
                on_device_lost=self._on_usb_camera_lost,
            )

        # CSI Camera scanner (requires picamera2)
        self._csi_scanner: Optional[CSIScanner] = None
        if PICAMERA2_AVAILABLE:
            self._csi_scanner = CSIScanner(
                on_device_found=self._on_csi_camera_found,
                on_device_lost=self._on_csi_camera_lost,
            )

        # UART scanner (always available - checks fixed paths)
        self._uart_scanner = UARTScanner(
            on_device_found=self._on_uart_device_found,
            on_device_lost=self._on_uart_device_lost,
        )

        # Device tracking
        self._usb_devices: Dict[str, DeviceInfo] = {}
        self._xbee_dongles: Dict[str, XBeeDongleInfo] = {}
        self._network_devices: Dict[str, DeviceInfo] = {}
        self._audio_devices: Dict[str, DeviceInfo] = {}
        self._internal_devices: Dict[str, DeviceInfo] = {}
        self._camera_devices: Dict[str, DeviceInfo] = {}
        self._uart_devices: Dict[str, DeviceInfo] = {}
        self._connected_devices: Set[str] = set()  # device_ids that are connected

        # Callbacks
        self._on_devices_changed: Optional[DevicesChangedCallback] = None
        self._on_device_connected: Optional[DeviceConnectedCallback] = None
        self._on_device_disconnected: Optional[DeviceDisconnectedCallback] = None
        self._on_save_connection_state: Optional[DeviceConnectionStateCallback] = None
        self._on_load_connection_state: Optional[LoadDeviceConnectionStateCallback] = None

        # State
        self._scanning_enabled = False
        self._pending_auto_connect_modules: Set[str] = set()  # Modules that should auto-connect when device found

        # Enabled connections: which interface+device combinations to scan for
        # By default, all connections are enabled
        self._enabled_connections: Set[ConnectionKey] = set()
        self._init_default_enabled_connections()

        # XBee data routing callback (set by logger system to route data to modules)
        self._xbee_data_router: Optional[Callable[[str, str], Awaitable[None]]] = None

        # Wireless transport registry - maps node_id to XBeeTransport
        self._wireless_transports: Dict[str, XBeeTransport] = {}

    def _init_default_enabled_connections(self) -> None:
        """Initialize with all connections enabled by default."""
        available = get_available_connections()
        for interface, families in available.items():
            for family in families:
                self._enabled_connections.add((interface, family))

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

    def set_save_connection_state_callback(self, callback: DeviceConnectionStateCallback) -> None:
        """Set callback for saving device connection state to config."""
        self._on_save_connection_state = callback

    def set_load_connection_state_callback(self, callback: LoadDeviceConnectionStateCallback) -> None:
        """Set callback for loading device connection state from config."""
        self._on_load_connection_state = callback

    def set_pending_auto_connect(self, module_id: str) -> None:
        """Mark a module as pending auto-connect when its device is discovered."""
        self._pending_auto_connect_modules.add(module_id)
        logger.info(f"Module {module_id} marked for auto-connect when device found")

    def clear_pending_auto_connect(self, module_id: str) -> None:
        """Clear pending auto-connect for a module."""
        self._pending_auto_connect_modules.discard(module_id)

    # =========================================================================
    # Enabled Connections Management
    # =========================================================================

    def get_enabled_connections(self) -> Set[ConnectionKey]:
        """Get the set of enabled interface+device family combinations."""
        return set(self._enabled_connections)

    def set_enabled_connections(self, connections: Set[ConnectionKey]) -> None:
        """Set which interface+device combinations are enabled for scanning."""
        self._enabled_connections = set(connections)
        logger.info(f"Enabled connections updated: {len(connections)} combinations")

    def is_connection_enabled(self, interface: InterfaceType, family: DeviceFamily) -> bool:
        """Check if a specific interface+device combination is enabled."""
        return (interface, family) in self._enabled_connections

    def set_connection_enabled(self, interface: InterfaceType, family: DeviceFamily, enabled: bool) -> None:
        """Enable or disable a specific interface+device combination."""
        key = (interface, family)
        if enabled:
            self._enabled_connections.add(key)
            logger.info(f"Enabled connection: {interface.value} > {family.value}")
        else:
            self._enabled_connections.discard(key)
            logger.info(f"Disabled connection: {interface.value} > {family.value}")

    def _is_device_enabled(self, spec) -> bool:
        """Check if a device should be tracked based on enabled connections."""
        # Coordinators are always tracked (they enable XBee devices)
        if spec.is_coordinator:
            # But only if any XBee connections are enabled
            return any(
                interface == InterfaceType.XBEE
                for interface, _ in self._enabled_connections
            )
        return (spec.interface_type, spec.family) in self._enabled_connections

    def set_xbee_data_router(self, router: Callable[[str, str], Awaitable[None]]) -> None:
        """
        Set callback for routing XBee data to modules.

        Args:
            router: Async callback (node_id, data) -> None
        """
        self._xbee_data_router = router
        # Also wire up the XBee manager's data callback
        if self._xbee_manager:
            self._xbee_manager.on_data_received = self._on_xbee_data_received

    async def _on_xbee_data_received(self, node_id: str, data: str) -> None:
        """Route incoming XBee data to the appropriate module."""
        # Only route if device is connected to a module
        if node_id not in self._connected_devices:
            logger.debug(f"Ignoring XBee data from unconnected device: {node_id}")
            return

        if self._xbee_data_router:
            await self._xbee_data_router(node_id, data)

    # =========================================================================
    # Scanning Control
    # =========================================================================

    async def start_scanning(self) -> None:
        """Start USB, XBee, network, audio, and internal device scanning."""
        if self._scanning_enabled:
            return

        self._scanning_enabled = True
        await self._usb_scanner.start()

        if self._xbee_manager:
            await self._xbee_manager.start()

        if self._network_scanner:
            await self._network_scanner.start()

        if self._audio_scanner:
            await self._audio_scanner.start()

        # Internal devices are always available
        await self._internal_scanner.start()

        # USB Camera devices
        if self._usb_camera_scanner:
            await self._usb_camera_scanner.start()

        # CSI Camera devices (Pi cameras)
        if self._csi_scanner:
            await self._csi_scanner.start()

        # UART devices (fixed path check)
        await self._uart_scanner.start()

        logger.info("Device scanning enabled")

    async def stop_scanning(self) -> None:
        """Stop USB, XBee, network, audio, and internal device scanning."""
        if not self._scanning_enabled:
            return

        self._scanning_enabled = False
        await self._usb_scanner.stop()

        if self._xbee_manager:
            await self._xbee_manager.stop()

        if self._network_scanner:
            await self._network_scanner.stop()

        if self._audio_scanner:
            await self._audio_scanner.stop()

        await self._internal_scanner.stop()

        if self._usb_camera_scanner:
            await self._usb_camera_scanner.stop()

        if self._csi_scanner:
            await self._csi_scanner.stop()

        await self._uart_scanner.stop()

        # Clear device tracking but notify about disconnections first
        for device_id in list(self._connected_devices):
            await self._disconnect_device_internal(device_id)

        self._usb_devices.clear()
        self._xbee_dongles.clear()
        self._network_devices.clear()
        self._audio_devices.clear()
        self._internal_devices.clear()
        self._camera_devices.clear()
        self._uart_devices.clear()
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

    def get_network_devices(self) -> list[DeviceInfo]:
        """Get all discovered network devices (e.g., eye trackers)."""
        return list(self._network_devices.values())

    def get_audio_devices(self) -> list[DeviceInfo]:
        """Get all discovered audio devices (e.g., USB microphones)."""
        return list(self._audio_devices.values())

    def get_internal_devices(self) -> list[DeviceInfo]:
        """Get all internal/virtual devices (e.g., Notes)."""
        return list(self._internal_devices.values())

    def get_camera_devices(self) -> list[DeviceInfo]:
        """Get all discovered camera devices (USB and Pi cameras)."""
        return list(self._camera_devices.values())

    def get_uart_devices(self) -> list[DeviceInfo]:
        """Get all discovered UART devices (e.g., GPS on /dev/serial0)."""
        return list(self._uart_devices.values())

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

        # Network devices
        for device in self._network_devices.values():
            if device.module_id == module_id:
                devices.append(device)

        # Audio devices
        for device in self._audio_devices.values():
            if device.module_id == module_id:
                devices.append(device)

        # Internal devices
        for device in self._internal_devices.values():
            if device.module_id == module_id:
                devices.append(device)

        # Camera devices
        for device in self._camera_devices.values():
            if device.module_id == module_id:
                devices.append(device)

        # UART devices
        for device in self._uart_devices.values():
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

        # Save connection state to config
        if self._on_save_connection_state and device.module_id:
            await self._on_save_connection_state(device.module_id, True)

        # Notify callback
        if self._on_device_connected:
            await self._on_device_connected(device)

        return True

    async def disconnect_device(self, device_id: str) -> None:
        """Disconnect a device from its module."""
        await self._disconnect_device_internal(device_id)
        self._notify_changed()

    async def _disconnect_device_internal(self, device_id: str, save_state: bool = True) -> None:
        """Internal disconnect without UI notification."""
        device = self._find_device(device_id)
        if device and device_id in self._connected_devices:
            module_id = device.module_id
            device.state = ConnectionState.DISCOVERED
            self._connected_devices.discard(device_id)

            logger.info(f"Device disconnected: {device_id}")

            # Save connection state to config (only if explicitly disconnected)
            if save_state and self._on_save_connection_state and module_id:
                await self._on_save_connection_state(module_id, False)

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
        spec = usb_device.spec

        # Check if this device type is enabled
        if not self._is_device_enabled(spec):
            logger.debug(f"Ignoring disabled device type: {spec.display_name} ({spec.interface_type.value})")
            return

        # Check if XBee dongle
        if usb_device.device_type == DeviceType.XBEE_COORDINATOR:
            self._xbee_dongles[usb_device.port] = XBeeDongleInfo(port=usb_device.port)
            logger.info(f"XBee dongle discovered: {usb_device.port}")
        else:
            device_info = DeviceInfo(
                device_id=usb_device.port,
                device_type=usb_device.device_type,
                family=spec.family,
                interface_type=spec.interface_type,
                display_name=f"{spec.display_name} on {usb_device.port}",
                port=usb_device.port,
                baudrate=spec.baudrate,
                module_id=spec.module_id,
                is_wireless=False,
            )
            self._usb_devices[usb_device.port] = device_info
            logger.info(f"USB device discovered: {device_info.display_name}")

            # Check if this module should auto-connect
            if spec.module_id in self._pending_auto_connect_modules:
                logger.info(f"Auto-connecting device {usb_device.port} for module {spec.module_id}")
                self._pending_auto_connect_modules.discard(spec.module_id)
                # Connect the device (this will trigger the connected callback)
                await self.connect_device(usb_device.port)
                return  # _notify_changed is called inside connect_device

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

        # Check if this device type is enabled
        if not self._is_device_enabled(spec):
            logger.debug(f"Ignoring disabled wireless device: {spec.display_name}")
            return

        dongle = self._xbee_dongles[dongle_port]

        device_info = DeviceInfo(
            device_id=wireless_device.node_id,
            device_type=wireless_device.device_type,
            family=wireless_device.family,
            interface_type=spec.interface_type,
            display_name=spec.display_name,  # Use simple name like "DRT" or "VOG"
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
        # Destroy transport first (unregisters handler)
        await self.destroy_wireless_transport(node_id)

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
    # Network Scanner Callbacks
    # =========================================================================

    async def _on_network_device_found(self, network_device: DiscoveredNetworkDevice) -> None:
        """Handle network device discovery (e.g., eye tracker via mDNS)."""
        spec = get_spec(DeviceType.PUPIL_LABS_NEON)

        # Check if this device type is enabled
        if not self._is_device_enabled(spec):
            logger.debug(f"Ignoring disabled network device: {spec.display_name}")
            return

        # Use the device name from mDNS as the display name
        display_name = f"{network_device.name} ({network_device.address})"

        device_info = DeviceInfo(
            device_id=network_device.device_id,
            device_type=DeviceType.PUPIL_LABS_NEON,
            family=DeviceFamily.EYE_TRACKER,
            interface_type=spec.interface_type,
            display_name=display_name,
            port=None,  # No serial port for network devices
            baudrate=0,
            module_id=spec.module_id,
            is_network=True,
            network_address=network_device.address,
            network_port=network_device.port,
        )

        self._network_devices[network_device.device_id] = device_info
        logger.info(f"Network device discovered: {display_name}")

        # Check if this module should auto-connect
        if spec.module_id in self._pending_auto_connect_modules:
            logger.info(f"Auto-connecting device {network_device.device_id} for module {spec.module_id}")
            self._pending_auto_connect_modules.discard(spec.module_id)
            await self.connect_device(network_device.device_id)
            return  # _notify_changed is called inside connect_device

        self._notify_changed()

    async def _on_network_device_lost(self, device_id: str) -> None:
        """Handle network device loss."""
        # Disconnect if connected
        if device_id in self._connected_devices:
            await self._disconnect_device_internal(device_id)

        device = self._network_devices.pop(device_id, None)
        if device:
            logger.info(f"Network device lost: {device.display_name}")

        self._notify_changed()

    # =========================================================================
    # Audio Scanner Callbacks
    # =========================================================================

    async def _on_audio_device_found(self, audio_device: DiscoveredAudioDevice) -> None:
        """Handle audio device discovery (e.g., USB microphone)."""
        spec = get_spec(DeviceType.USB_MICROPHONE)

        # Check if this device type is enabled
        if not self._is_device_enabled(spec):
            logger.debug(f"Ignoring disabled audio device: {spec.display_name}")
            return

        device_info = DeviceInfo(
            device_id=audio_device.device_id,
            device_type=DeviceType.USB_MICROPHONE,
            family=DeviceFamily.AUDIO,
            interface_type=spec.interface_type,
            display_name=audio_device.name,
            port=None,  # No serial port for audio devices
            baudrate=0,
            module_id=spec.module_id,
            is_audio=True,
            sounddevice_index=audio_device.sounddevice_index,
            audio_channels=audio_device.channels,
            audio_sample_rate=audio_device.sample_rate,
        )

        self._audio_devices[audio_device.device_id] = device_info
        logger.info(f"Audio device discovered: {audio_device.name}")

        # Check if this module should auto-connect
        if spec.module_id in self._pending_auto_connect_modules:
            logger.info(f"Auto-connecting device {audio_device.device_id} for module {spec.module_id}")
            self._pending_auto_connect_modules.discard(spec.module_id)
            await self.connect_device(audio_device.device_id)
            return  # _notify_changed is called inside connect_device

        self._notify_changed()

    async def _on_audio_device_lost(self, device_id: str) -> None:
        """Handle audio device loss."""
        # Disconnect if connected
        if device_id in self._connected_devices:
            await self._disconnect_device_internal(device_id)

        device = self._audio_devices.pop(device_id, None)
        if device:
            logger.info(f"Audio device lost: {device.display_name}")

        self._notify_changed()

    # =========================================================================
    # Internal Device Scanner Callbacks
    # =========================================================================

    async def _on_internal_device_found(self, internal_device: DiscoveredInternalDevice) -> None:
        """Handle internal device discovery (e.g., Notes module)."""
        spec = internal_device.spec

        # Check if this device type is enabled
        if not self._is_device_enabled(spec):
            logger.debug(f"Ignoring disabled internal device: {spec.display_name}")
            return

        device_info = DeviceInfo(
            device_id=internal_device.device_id,
            device_type=internal_device.device_type,
            family=spec.family,
            interface_type=spec.interface_type,
            display_name=spec.display_name,
            port=None,  # No physical port for internal devices
            baudrate=0,
            module_id=spec.module_id,
            is_internal=True,
        )

        self._internal_devices[internal_device.device_id] = device_info
        logger.info(f"Internal device discovered: {spec.display_name}")

        # Check if this module should auto-connect
        if spec.module_id in self._pending_auto_connect_modules:
            logger.info(f"Auto-connecting device {internal_device.device_id} for module {spec.module_id}")
            self._pending_auto_connect_modules.discard(spec.module_id)
            await self.connect_device(internal_device.device_id)
            return  # _notify_changed is called inside connect_device

        self._notify_changed()

    async def _on_internal_device_lost(self, device_id: str) -> None:
        """Handle internal device loss (typically only on shutdown)."""
        # Disconnect if connected
        if device_id in self._connected_devices:
            await self._disconnect_device_internal(device_id)

        device = self._internal_devices.pop(device_id, None)
        if device:
            logger.info(f"Internal device lost: {device.display_name}")

        self._notify_changed()

    # =========================================================================
    # USB Camera Scanner Callbacks
    # =========================================================================

    async def _on_usb_camera_found(self, camera: DiscoveredUSBCamera) -> None:
        """Handle USB camera device discovery."""
        spec = get_spec(DeviceType.USB_CAMERA)

        # Check if this device type is enabled
        if not self._is_device_enabled(spec):
            logger.debug(f"Ignoring disabled USB camera device: {spec.display_name}")
            return

        device_info = DeviceInfo(
            device_id=camera.device_id,
            device_type=DeviceType.USB_CAMERA,
            family=DeviceFamily.CAMERA,
            interface_type=spec.interface_type,
            display_name=camera.friendly_name,
            port=None,  # Cameras don't use serial ports
            baudrate=0,
            module_id=spec.module_id,
            is_camera=True,
            camera_type="usb",
            camera_stable_id=camera.stable_id,
            camera_dev_path=camera.dev_path,
            camera_hw_model=camera.hw_model,
            camera_location=camera.location_hint,
        )

        self._camera_devices[camera.device_id] = device_info
        logger.info(f"USB camera discovered: {camera.friendly_name} ({camera.device_id})")

        # Check if this module should auto-connect
        if spec.module_id in self._pending_auto_connect_modules:
            logger.info(f"Auto-connecting USB camera {camera.device_id} for module {spec.module_id}")
            self._pending_auto_connect_modules.discard(spec.module_id)
            await self.connect_device(camera.device_id)
            return  # _notify_changed is called inside connect_device

        self._notify_changed()

    async def _on_usb_camera_lost(self, device_id: str) -> None:
        """Handle USB camera device removal."""
        # Disconnect if connected
        if device_id in self._connected_devices:
            await self._disconnect_device_internal(device_id)

        device = self._camera_devices.pop(device_id, None)
        if device:
            logger.info(f"USB camera lost: {device.display_name} ({device_id})")

        self._notify_changed()

    # =========================================================================
    # CSI Camera Scanner Callbacks
    # =========================================================================

    async def _on_csi_camera_found(self, camera: DiscoveredCSICamera) -> None:
        """Handle CSI (Pi) camera device discovery."""
        spec = get_spec(DeviceType.PI_CAMERA)

        # Check if this device type is enabled
        if not self._is_device_enabled(spec):
            logger.debug(f"Ignoring disabled CSI camera device: {spec.display_name}")
            return

        device_info = DeviceInfo(
            device_id=camera.device_id,
            device_type=DeviceType.PI_CAMERA,
            family=DeviceFamily.CAMERA,
            interface_type=spec.interface_type,
            display_name=camera.friendly_name,
            port=None,  # Cameras don't use serial ports
            baudrate=0,
            module_id=spec.module_id,
            is_camera=True,
            camera_type="picam",
            camera_stable_id=camera.stable_id,
            camera_dev_path=None,  # CSI cameras don't have /dev/video paths
            camera_hw_model=camera.hw_model,
            camera_location=camera.location_hint,
        )

        self._camera_devices[camera.device_id] = device_info
        logger.info(f"CSI camera discovered: {camera.friendly_name} ({camera.device_id})")

        # Check if this module should auto-connect
        if spec.module_id in self._pending_auto_connect_modules:
            logger.info(f"Auto-connecting CSI camera {camera.device_id} for module {spec.module_id}")
            self._pending_auto_connect_modules.discard(spec.module_id)
            await self.connect_device(camera.device_id)
            return  # _notify_changed is called inside connect_device

        self._notify_changed()

    async def _on_csi_camera_lost(self, device_id: str) -> None:
        """Handle CSI camera device removal."""
        # Disconnect if connected
        if device_id in self._connected_devices:
            await self._disconnect_device_internal(device_id)

        device = self._camera_devices.pop(device_id, None)
        if device:
            logger.info(f"CSI camera lost: {device.display_name} ({device_id})")

        self._notify_changed()

    # =========================================================================
    # UART Scanner Callbacks
    # =========================================================================

    async def _on_uart_device_found(self, uart_device: DiscoveredUARTDevice) -> None:
        """Handle UART device discovery (e.g., GPS on /dev/serial0)."""
        spec = uart_device.spec

        # Check if this device type is enabled
        if not self._is_device_enabled(spec):
            logger.debug(f"Ignoring disabled UART device: {spec.display_name}")
            return

        device_info = DeviceInfo(
            device_id=uart_device.device_id,
            device_type=uart_device.device_type,
            family=spec.family,
            interface_type=spec.interface_type,
            display_name=spec.display_name,
            port=uart_device.path,  # Use the UART path as port
            baudrate=spec.baudrate,
            module_id=spec.module_id,
            is_uart=True,
            uart_path=uart_device.path,
        )

        self._uart_devices[uart_device.device_id] = device_info
        logger.info(f"UART device discovered: {spec.display_name} at {uart_device.path}")

        # Check if this module should auto-connect
        if spec.module_id in self._pending_auto_connect_modules:
            logger.info(f"Auto-connecting UART device {uart_device.device_id} for module {spec.module_id}")
            self._pending_auto_connect_modules.discard(spec.module_id)
            await self.connect_device(uart_device.device_id)
            return  # _notify_changed is called inside connect_device

        self._notify_changed()

    async def _on_uart_device_lost(self, device_id: str) -> None:
        """Handle UART device loss (typically only on shutdown)."""
        # Disconnect if connected
        if device_id in self._connected_devices:
            await self._disconnect_device_internal(device_id)

        device = self._uart_devices.pop(device_id, None)
        if device:
            logger.info(f"UART device lost: {device.display_name} ({device_id})")

        self._notify_changed()

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _find_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Find device by ID (checks USB, wireless, network, audio, internal, camera, and UART devices)."""
        # Check USB devices
        if device_id in self._usb_devices:
            return self._usb_devices[device_id]

        # Check wireless devices under dongles
        for dongle in self._xbee_dongles.values():
            if device_id in dongle.child_devices:
                return dongle.child_devices[device_id]

        # Check network devices
        if device_id in self._network_devices:
            return self._network_devices[device_id]

        # Check audio devices
        if device_id in self._audio_devices:
            return self._audio_devices[device_id]

        # Check internal devices
        if device_id in self._internal_devices:
            return self._internal_devices[device_id]

        # Check camera devices
        if device_id in self._camera_devices:
            return self._camera_devices[device_id]

        # Check UART devices
        if device_id in self._uart_devices:
            return self._uart_devices[device_id]

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

    # =========================================================================
    # Wireless Transport Management
    # =========================================================================

    async def create_wireless_transport(self, node_id: str) -> Optional[XBeeTransport]:
        """
        Create an XBeeTransport for a wireless device.

        Creates the transport, connects it, and registers it for message routing.
        The transport is owned by this manager and should be retrieved by modules
        via get_wireless_transport().

        Args:
            node_id: The wireless device's node ID (e.g., "wVOG_01")

        Returns:
            The created transport, or None if creation failed
        """
        # Return existing transport if already created
        if node_id in self._wireless_transports:
            logger.debug(f"Returning existing transport for {node_id}")
            return self._wireless_transports[node_id]

        if not self._xbee_manager:
            logger.error("Cannot create wireless transport: XBee manager not available")
            return None

        coordinator = self._xbee_manager.coordinator
        remote = self._xbee_manager.get_remote_device(node_id)

        if not coordinator:
            logger.error(f"Cannot create wireless transport for {node_id}: no coordinator")
            return None

        if not remote:
            logger.error(f"Cannot create wireless transport for {node_id}: remote device not found")
            return None

        # Create transport
        transport = XBeeTransport(remote, coordinator, node_id)

        # Connect (marks as ready)
        if not await transport.connect():
            logger.error(f"Failed to connect wireless transport for {node_id}")
            return None

        # Register for message routing - handler is called directly from XBee thread
        self._xbee_manager.register_data_handler(node_id, transport.handle_received_data)

        # Store in registry
        self._wireless_transports[node_id] = transport
        logger.info(f"Created wireless transport for {node_id}")

        return transport

    def get_wireless_transport(self, node_id: str) -> Optional[XBeeTransport]:
        """
        Get an existing wireless transport by node ID.

        Args:
            node_id: The wireless device's node ID

        Returns:
            The transport, or None if not found
        """
        return self._wireless_transports.get(node_id)

    async def destroy_wireless_transport(self, node_id: str) -> None:
        """
        Destroy a wireless transport and unregister its handler.

        Args:
            node_id: The wireless device's node ID
        """
        transport = self._wireless_transports.pop(node_id, None)
        if transport:
            # Unregister from message routing
            if self._xbee_manager:
                self._xbee_manager.unregister_data_handler(node_id)

            # Disconnect transport
            await transport.disconnect()
            logger.info(f"Destroyed wireless transport for {node_id}")
