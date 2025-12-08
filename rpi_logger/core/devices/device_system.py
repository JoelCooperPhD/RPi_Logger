"""
Device System - Unified facade for the new device architecture.

This module provides a single entry point (DeviceSystem) that wires together
all the components of the new architecture:
- DeviceCatalog (metadata)
- DeviceSelectionModel (state)
- DeviceLifecycleManager (unified event handling)
- DeviceUIController (UI data transformation)
- ScannerEventAdapter (adapts existing scanners)
- All device scanners (USB, XBee, Network, Audio, Camera, etc.)

Usage:
    # Create the system
    system = DeviceSystem()

    # Start/stop scanning
    await system.start_scanning()
    await system.stop_scanning()

    # Get UI component
    panel = DevicesPanel(parent, system.ui_controller)

    # Handle device events
    system.set_on_connect_device(handle_connect)
    system.set_on_disconnect_device(handle_disconnect)

    # Load/save config
    system.load_enabled_connections(config_string)
    config_string = system.save_enabled_connections()
"""

import asyncio
from typing import Callable, Awaitable, Any, Optional

from rpi_logger.core.logging_utils import get_module_logger
from .catalog import DeviceCatalog
from .selection import DeviceSelectionModel, ConnectionKey
from .lifecycle import DeviceLifecycleManager, DeviceInfo
from .scanner_adapter import ScannerEventAdapter
from .device_registry import DeviceFamily, InterfaceType

# Import scanners
from .usb_scanner import USBScanner
from .xbee_manager import XBeeManager, XBEE_AVAILABLE
from .network_scanner import NetworkScanner, ZEROCONF_AVAILABLE
from .audio_scanner import AudioScanner, SOUNDDEVICE_AVAILABLE
from .internal_scanner import InternalDeviceScanner
from .usb_camera_scanner import USBCameraScanner, CV2_AVAILABLE
from .csi_scanner import CSIScanner, PICAMERA2_AVAILABLE
from .uart_scanner import UARTScanner

logger = get_module_logger("DeviceSystem")


# UI controller is imported lazily to avoid circular imports
# (device_controller imports from devices, devices/__init__ imports device_system)
DeviceUIController = None  # Will be set lazily


def _get_ui_controller_class():
    """Lazily import DeviceUIController to avoid circular imports."""
    global DeviceUIController
    if DeviceUIController is None:
        try:
            from rpi_logger.core.ui.device_controller import DeviceUIController as _DeviceUIController
            DeviceUIController = _DeviceUIController
        except Exception as e:
            logger.debug(f"UI controller not available: {e}")
            return None
    return DeviceUIController


class DeviceSystem:
    """
    Unified facade for the device management system.

    This class provides a single point of integration for the new
    device architecture. It creates and wires all components together,
    and provides a clean API for the application layer.

    The system handles:
    - Device discovery and removal (via scanners)
    - Connection type enable/disable
    - Device connect/disconnect
    - UI data transformation
    - Config persistence

    Thread Safety:
        This class is designed to be used from the main thread.
        Scanner callbacks may come from other threads and should
        be marshaled to the main thread before calling this system.
    """

    def __init__(self):
        """Initialize the device system."""
        # Core components
        self._catalog = DeviceCatalog
        self._selection = DeviceSelectionModel()
        self._lifecycle = DeviceLifecycleManager(self._selection, self._catalog)

        # UI controller (optional, lazily imported)
        self._ui_controller: Any = None
        UIControllerClass = _get_ui_controller_class()
        if UIControllerClass:
            self._ui_controller = UIControllerClass(
                self._selection,
                self._lifecycle,
                self._catalog,
            )

        # Scanner adapter
        self._adapter = ScannerEventAdapter(self._lifecycle.handle_event)

        # Create scanners
        self._usb_scanner = USBScanner(
            on_device_found=self._adapter.on_usb_device_found,
            on_device_lost=self._adapter.on_usb_device_lost,
        )

        self._xbee_manager: Optional[XBeeManager] = None
        if XBEE_AVAILABLE:
            self._xbee_manager = XBeeManager()
            # XBee wiring is done via wire_xbee_callbacks() after dongle port is available

        self._network_scanner: Optional[NetworkScanner] = None
        if ZEROCONF_AVAILABLE:
            self._network_scanner = NetworkScanner(
                on_device_found=self._adapter.on_network_device_found,
                on_device_lost=self._adapter.on_network_device_lost,
            )

        self._audio_scanner: Optional[AudioScanner] = None
        if SOUNDDEVICE_AVAILABLE:
            self._audio_scanner = AudioScanner(
                on_device_found=self._adapter.on_audio_device_found,
                on_device_lost=self._adapter.on_audio_device_lost,
            )

        self._internal_scanner = InternalDeviceScanner(
            on_device_found=self._adapter.on_internal_device_found,
            on_device_lost=self._adapter.on_internal_device_lost,
        )

        self._usb_camera_scanner: Optional[USBCameraScanner] = None
        if CV2_AVAILABLE:
            self._usb_camera_scanner = USBCameraScanner(
                on_device_found=self._adapter.on_usb_camera_found,
                on_device_lost=self._adapter.on_usb_camera_lost,
            )

        self._csi_scanner: Optional[CSIScanner] = None
        if PICAMERA2_AVAILABLE:
            self._csi_scanner = CSIScanner(
                on_device_found=self._adapter.on_csi_camera_found,
                on_device_lost=self._adapter.on_csi_camera_lost,
            )

        self._uart_scanner = UARTScanner(
            on_device_found=self._adapter.on_uart_device_found,
            on_device_lost=self._adapter.on_uart_device_lost,
        )

        # Scanner registry: maps (interface, family) to the scanner that handles it
        # This enables generic reannouncement when connections are enabled
        self._scanner_registry: dict[tuple[InterfaceType, DeviceFamily], Any] = {}
        self._build_scanner_registry()

        # Scanning state
        self._scanning_enabled = False

        # Application callbacks
        self._on_connection_changed: Callable[[InterfaceType, DeviceFamily, bool], Awaitable[None] | None] | None = None
        self._on_connect_device: Callable[[str], Awaitable[None] | None] | None = None
        self._on_disconnect_device: Callable[[str], Awaitable[None] | None] | None = None
        self._on_devices_changed: Callable[[], None] | None = None
        self._on_xbee_dongle_connected: Callable[[str], Awaitable[None] | None] | None = None
        self._on_xbee_dongle_disconnected: Callable[[str], Awaitable[None] | None] | None = None

        # Track pending device operations to prevent duplicate concurrent requests
        # (e.g., rapid clicks creating multiple connect tasks for the same device)
        self._pending_device_ops: set[str] = set()

        # Wire internal callbacks
        self._selection.add_connection_observer(self._on_selection_changed)
        self._lifecycle.add_change_observer(self._on_lifecycle_changed)

        # Wire UI controller callbacks if available
        if self._ui_controller:
            self._ui_controller.set_connection_changed_callback(self._handle_ui_connection_toggle)
            self._ui_controller.set_connect_device_callback(self._handle_ui_connect)
            self._ui_controller.set_disconnect_device_callback(self._handle_ui_disconnect)

    def _build_scanner_registry(self) -> None:
        """Build the scanner registry mapping (interface, family) to scanners.

        This registry enables generic device reannouncement when connections
        are enabled, eliminating the need for if/elif chains.
        """
        # USB devices by family
        if self._usb_scanner:
            self._scanner_registry[(InterfaceType.USB, DeviceFamily.DRT)] = self._usb_scanner
            self._scanner_registry[(InterfaceType.USB, DeviceFamily.VOG)] = self._usb_scanner

        if self._audio_scanner:
            self._scanner_registry[(InterfaceType.USB, DeviceFamily.AUDIO)] = self._audio_scanner

        if self._usb_camera_scanner:
            self._scanner_registry[(InterfaceType.USB, DeviceFamily.CAMERA)] = self._usb_camera_scanner

        # Network devices
        if self._network_scanner:
            self._scanner_registry[(InterfaceType.NETWORK, DeviceFamily.EYE_TRACKER)] = self._network_scanner

        # UART devices
        if self._uart_scanner:
            self._scanner_registry[(InterfaceType.UART, DeviceFamily.GPS)] = self._uart_scanner

        # Internal/virtual devices
        if self._internal_scanner:
            self._scanner_registry[(InterfaceType.INTERNAL, DeviceFamily.INTERNAL)] = self._internal_scanner

        # CSI cameras (if available)
        if self._csi_scanner:
            self._scanner_registry[(InterfaceType.CSI, DeviceFamily.CAMERA)] = self._csi_scanner

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def catalog(self) -> type[DeviceCatalog]:
        """Get the device catalog."""
        return self._catalog

    @property
    def selection(self) -> DeviceSelectionModel:
        """Get the selection model (for advanced use)."""
        return self._selection

    @property
    def lifecycle(self) -> DeviceLifecycleManager:
        """Get the lifecycle manager (for advanced use)."""
        return self._lifecycle

    @property
    def ui_controller(self) -> Any:
        """Get the UI controller (may be None if UI not available)."""
        return self._ui_controller

    @property
    def adapter(self) -> ScannerEventAdapter:
        """Get the scanner event adapter."""
        return self._adapter

    @property
    def xbee_manager(self) -> Optional[XBeeManager]:
        """Get the XBee manager (may be None if XBee not available)."""
        return self._xbee_manager

    @property
    def usb_scanner(self) -> USBScanner:
        """Get the USB scanner."""
        return self._usb_scanner

    # =========================================================================
    # Application Callbacks
    # =========================================================================

    def set_on_connection_changed(
        self,
        callback: Callable[[InterfaceType, DeviceFamily, bool], Awaitable[None] | None]
    ) -> None:
        """
        Set callback for when a connection type is enabled/disabled.

        The callback receives (interface, family, enabled).
        """
        self._on_connection_changed = callback

    def set_on_connect_device(
        self,
        callback: Callable[[str], Awaitable[None] | None]
    ) -> None:
        """
        Set callback for when user wants to connect a device.

        The callback receives the device_id.
        """
        self._on_connect_device = callback
        self._lifecycle.set_connect_callback(self._wrap_async_callback(callback))

    def set_on_disconnect_device(
        self,
        callback: Callable[[str], Awaitable[None] | None]
    ) -> None:
        """
        Set callback for when user wants to disconnect a device.

        The callback receives the device_id.
        """
        self._on_disconnect_device = callback
        self._lifecycle.set_disconnect_callback(self._wrap_async_callback(callback))

    def set_on_devices_changed(self, callback: Callable[[], None]) -> None:
        """
        Set callback for when the device list changes.

        Called when devices are discovered or lost.
        """
        self._on_devices_changed = callback

    def _wrap_async_callback(
        self,
        callback: Callable[..., Awaitable[None] | None]
    ) -> Callable[..., Awaitable[None]]:
        """Wrap a callback to ensure it returns an awaitable."""
        async def wrapper(*args, **kwargs):
            result = callback(*args, **kwargs)
            if result is not None:
                await result
        return wrapper

    # =========================================================================
    # Scanner Wiring
    # =========================================================================

    def wire_usb_scanner(self, scanner: Any) -> None:
        """Wire the USB scanner to use event-based handling."""
        scanner.set_device_found_callback(self._adapter.on_usb_device_found)
        scanner.set_device_lost_callback(self._adapter.on_usb_device_lost)
        logger.info("Wired USB scanner to DeviceSystem")

    def wire_xbee_manager(self, manager: Any, get_dongle_port: Callable[[], str | None]) -> None:
        """
        Wire the XBee manager to use event-based handling.

        Args:
            manager: The XBee manager instance
            get_dongle_port: Function to get the current dongle port
        """
        async def on_wireless_found(device, remote_xbee):
            port = get_dongle_port()
            if port:
                await self._adapter.on_wireless_device_found(device, port)

        manager.set_wireless_device_found_callback(on_wireless_found)
        manager.set_wireless_device_lost_callback(self._adapter.on_wireless_device_lost)
        logger.info("Wired XBee manager to DeviceSystem")

    def wire_network_scanner(self, scanner: Any) -> None:
        """Wire the network scanner to use event-based handling."""
        scanner.set_device_found_callback(self._adapter.on_network_device_found)
        scanner.set_device_lost_callback(self._adapter.on_network_device_lost)
        logger.info("Wired network scanner to DeviceSystem")

    def wire_audio_scanner(self, scanner: Any) -> None:
        """Wire the audio scanner to use event-based handling."""
        scanner.set_device_found_callback(self._adapter.on_audio_device_found)
        scanner.set_device_lost_callback(self._adapter.on_audio_device_lost)
        logger.info("Wired audio scanner to DeviceSystem")

    def wire_internal_scanner(self, scanner: Any) -> None:
        """Wire the internal device scanner to use event-based handling."""
        scanner.set_device_found_callback(self._adapter.on_internal_device_found)
        scanner.set_device_lost_callback(self._adapter.on_internal_device_lost)
        logger.info("Wired internal scanner to DeviceSystem")

    def wire_usb_camera_scanner(self, scanner: Any) -> None:
        """Wire the USB camera scanner to use event-based handling."""
        scanner.set_device_found_callback(self._adapter.on_usb_camera_found)
        scanner.set_device_lost_callback(self._adapter.on_usb_camera_lost)
        logger.info("Wired USB camera scanner to DeviceSystem")

    def wire_csi_scanner(self, scanner: Any) -> None:
        """Wire the CSI camera scanner to use event-based handling."""
        scanner.set_device_found_callback(self._adapter.on_csi_camera_found)
        scanner.set_device_lost_callback(self._adapter.on_csi_camera_lost)
        logger.info("Wired CSI scanner to DeviceSystem")

    def wire_uart_scanner(self, scanner: Any) -> None:
        """Wire the UART scanner to use event-based handling."""
        scanner.set_device_found_callback(self._adapter.on_uart_device_found)
        scanner.set_device_lost_callback(self._adapter.on_uart_device_lost)
        logger.info("Wired UART scanner to DeviceSystem")

    # =========================================================================
    # Connection Management
    # =========================================================================

    def is_connection_enabled(self, interface: InterfaceType, family: DeviceFamily) -> bool:
        """Check if a connection type is enabled."""
        return self._selection.is_connection_enabled(interface, family)

    def set_connection_enabled(
        self,
        interface: InterfaceType,
        family: DeviceFamily,
        enabled: bool
    ) -> list[DeviceInfo]:
        """
        Enable or disable a connection type.

        Returns:
            List of devices that should be disconnected (if disabling).
        """
        # Update selection
        self._selection.set_connection_enabled(interface, family, enabled)

        # Get devices to disconnect
        if not enabled:
            return self._lifecycle.get_devices_to_disconnect_on_disable(interface, family)

        # If enabling, reannounce devices that may have been ignored
        if enabled:
            asyncio.create_task(self._reannounce_devices_for_connection(interface, family))

        return []

    async def _reannounce_devices_for_connection(
        self,
        interface: InterfaceType,
        family: DeviceFamily
    ) -> None:
        """Reannounce devices when a connection type is enabled.

        This ensures devices discovered before the connection was enabled
        get properly added to the lifecycle manager.
        """
        scanner = self._scanner_registry.get((interface, family))
        if scanner:
            logger.info(f"Reannouncing devices after enabling {interface.value}:{family.value}")
            await scanner.reannounce_devices()

    def get_enabled_connections(self) -> set[ConnectionKey]:
        """Get all enabled connection keys."""
        return self._selection.get_enabled_connections()

    # =========================================================================
    # Device Queries
    # =========================================================================

    def get_device(self, device_id: str) -> DeviceInfo | None:
        """Get a device by ID."""
        return self._lifecycle.get_device(device_id)

    def get_all_devices(self) -> list[DeviceInfo]:
        """Get all tracked devices."""
        return self._lifecycle.get_all_devices()

    def get_devices_by_family(self, family: DeviceFamily) -> list[DeviceInfo]:
        """Get devices of a specific family."""
        return self._lifecycle.get_devices_by_family(family)

    def get_connected_devices(self) -> list[DeviceInfo]:
        """Get all connected devices."""
        return self._lifecycle.get_connected_devices()

    def is_device_connected(self, device_id: str) -> bool:
        """Check if a device is connected."""
        return self._selection.is_device_connected(device_id)

    def get_devices_for_module(self, module_id: str) -> list[DeviceInfo]:
        """Get all devices that belong to a specific module."""
        return self._lifecycle.get_devices_for_module(module_id)

    # =========================================================================
    # Device State Management
    # =========================================================================

    def set_device_connected(self, device_id: str, connected: bool) -> None:
        """
        Update device connection state.

        Called by application when a device actually connects/disconnects.
        """
        self._lifecycle.set_device_connected(device_id, connected)

    def set_device_connecting(self, device_id: str) -> None:
        """
        Set device to CONNECTING state (yellow indicator).

        Called when user clicks to connect but before module acknowledges ready.
        """
        self._lifecycle.set_device_connecting(device_id)

    def is_device_connecting(self, device_id: str) -> bool:
        """Check if device is in CONNECTING state (yellow indicator)."""
        return self._selection.is_device_connecting(device_id)

    # =========================================================================
    # Config Persistence
    # =========================================================================

    def load_enabled_connections(self, data: str) -> None:
        """
        Load enabled connections from config string.

        Format: "USB:VOG,USB:DRT,XBee:VOG,..."
        """
        self._selection.deserialize_connections(data)

    def save_enabled_connections(self) -> str:
        """
        Save enabled connections to config string.

        Format: "USB:VOG,USB:DRT,XBee:VOG,..."
        """
        return self._selection.serialize_connections()

    # =========================================================================
    # Auto-Connect
    # =========================================================================

    def set_auto_connect_modules(self, module_ids: set[str]) -> None:
        """Set modules that should auto-connect when their device is found."""
        self._selection.set_auto_connect_modules(module_ids)

    def request_auto_connect(self, module_id: str) -> None:
        """Request auto-connect for a module."""
        self._selection.set_auto_connect(module_id, True)

    # =========================================================================
    # Internal Callbacks
    # =========================================================================

    def _on_selection_changed(self) -> None:
        """Called when selection model changes."""
        # Connection changes are handled by _handle_ui_connection_toggle
        pass

    def _on_lifecycle_changed(self) -> None:
        """Called when device list changes."""
        if self._on_devices_changed:
            self._on_devices_changed()

    def _handle_ui_connection_toggle(
        self,
        interface: InterfaceType,
        family: DeviceFamily,
        enabled: bool
    ) -> None:
        """Handle connection toggle from UI controller."""
        logger.info(f"Connection toggled: {interface.value}:{family.value} -> {enabled}")

        if self._on_connection_changed:
            result = self._on_connection_changed(interface, family, enabled)
            # If callback is async, schedule it
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)

    def _handle_ui_connect(self, device_id: str) -> None:
        """Handle device connect request from UI controller.

        Uses pending operations tracking to prevent duplicate concurrent
        connect attempts when user clicks rapidly.
        """
        # Prevent duplicate operations for the same device
        if device_id in self._pending_device_ops:
            logger.debug(f"Ignoring connect request - operation already pending: {device_id}")
            return

        if self._on_connect_device:
            self._pending_device_ops.add(device_id)
            result = self._on_connect_device(device_id)
            if asyncio.iscoroutine(result):
                task = asyncio.create_task(result)
                # Remove from pending when task completes
                task.add_done_callback(
                    lambda t, did=device_id: self._pending_device_ops.discard(did)
                )
            else:
                # Synchronous callback - operation is complete
                self._pending_device_ops.discard(device_id)

    def _handle_ui_disconnect(self, device_id: str) -> None:
        """Handle device disconnect request from UI controller.

        Uses pending operations tracking to prevent duplicate concurrent
        disconnect attempts when user clicks rapidly.
        """
        # Prevent duplicate operations for the same device
        if device_id in self._pending_device_ops:
            logger.debug(f"Ignoring disconnect request - operation already pending: {device_id}")
            return

        if self._on_disconnect_device:
            self._pending_device_ops.add(device_id)
            result = self._on_disconnect_device(device_id)
            if asyncio.iscoroutine(result):
                task = asyncio.create_task(result)
                # Remove from pending when task completes
                task.add_done_callback(
                    lambda t, did=device_id: self._pending_device_ops.discard(did)
                )
            else:
                # Synchronous callback - operation is complete
                self._pending_device_ops.discard(device_id)

    # =========================================================================
    # XBee Callbacks
    # =========================================================================

    def set_on_xbee_dongle_connected(
        self,
        callback: Callable[[str], Awaitable[None] | None]
    ) -> None:
        """Set callback for when an XBee dongle is connected."""
        self._on_xbee_dongle_connected = callback

    def set_on_xbee_dongle_disconnected(
        self,
        callback: Callable[[str], Awaitable[None] | None]
    ) -> None:
        """Set callback for when an XBee dongle is disconnected."""
        self._on_xbee_dongle_disconnected = callback

    def set_xbee_data_callback(
        self,
        callback: Callable[[str, bytes], Awaitable[None]]
    ) -> None:
        """Set callback for XBee data received from wireless devices."""
        if self._xbee_manager:
            self._xbee_manager.on_data_received = callback

    # =========================================================================
    # Scanning Lifecycle
    # =========================================================================

    async def start_scanning(self) -> None:
        """Start all device scanners."""
        if self._scanning_enabled:
            return

        self._scanning_enabled = True
        logger.info("Starting device scanning")

        # Start USB scanner
        await self._usb_scanner.start()

        # Start audio scanner
        if self._audio_scanner:
            await self._audio_scanner.start()

        # Start internal device scanner
        await self._internal_scanner.start()

        # Start USB camera scanner
        if self._usb_camera_scanner:
            await self._usb_camera_scanner.start()

        # Start CSI camera scanner
        if self._csi_scanner:
            await self._csi_scanner.start()

        # Start UART scanner
        await self._uart_scanner.start()

        # Start network scanner
        if self._network_scanner:
            await self._network_scanner.start()

        logger.info("Device scanning started")

    async def stop_scanning(self) -> None:
        """Stop all device scanners."""
        if not self._scanning_enabled:
            return

        self._scanning_enabled = False
        logger.info("Stopping device scanning")

        # Stop USB scanner
        await self._usb_scanner.stop()

        # Stop XBee manager
        if self._xbee_manager:
            await self._xbee_manager.stop()

        # Stop audio scanner
        if self._audio_scanner:
            await self._audio_scanner.stop()

        # Stop internal scanner
        await self._internal_scanner.stop()

        # Stop USB camera scanner
        if self._usb_camera_scanner:
            await self._usb_camera_scanner.stop()

        # Stop CSI camera scanner
        if self._csi_scanner:
            await self._csi_scanner.stop()

        # Stop UART scanner
        await self._uart_scanner.stop()

        # Stop network scanner
        if self._network_scanner:
            await self._network_scanner.stop()

        logger.info("Device scanning stopped")

    # =========================================================================
    # XBee Dongle Management
    # =========================================================================

    async def initialize_xbee_dongle(self, port: str) -> bool:
        """
        Initialize XBee dongle on the given port.

        Returns True if successful, False otherwise.
        """
        if not self._xbee_manager:
            logger.warning("XBee not available")
            return False

        try:
            # Wire XBee callbacks for wireless device discovery
            async def on_wireless_found(device, remote_xbee):
                await self._adapter.on_wireless_device_found(device, port)

            self._xbee_manager.on_device_discovered = on_wireless_found
            self._xbee_manager.on_device_lost = self._adapter.on_wireless_device_lost
            self._xbee_manager.on_dongle_connected = self._handle_xbee_dongle_connected
            self._xbee_manager.on_dongle_disconnected = self._handle_xbee_dongle_disconnected

            await self._xbee_manager.initialize(port)
            return True
        except Exception as e:
            logger.error(f"Failed to initialize XBee dongle: {e}")
            return False

    async def shutdown_xbee_dongle(self) -> None:
        """Shutdown the XBee dongle."""
        if self._xbee_manager:
            await self._xbee_manager.stop()

    def _handle_xbee_dongle_connected(self, port: str) -> None:
        """Handle XBee dongle connected."""
        if self._on_xbee_dongle_connected:
            result = self._on_xbee_dongle_connected(port)
            # Can't await here, application handles async

    def _handle_xbee_dongle_disconnected(self, port: str) -> None:
        """Handle XBee dongle disconnected."""
        if self._on_xbee_dongle_disconnected:
            result = self._on_xbee_dongle_disconnected(port)
            # Can't await here, application handles async

    # =========================================================================
    # XBee Transport (for wireless device communication)
    # =========================================================================

    async def create_wireless_transport(self, node_id: str) -> Any:
        """Create a transport for communicating with a wireless device."""
        if not self._xbee_manager:
            raise RuntimeError("XBee not available")
        return await self._xbee_manager.create_transport(node_id)

    def get_wireless_transport(self, node_id: str) -> Any:
        """Get existing transport for a wireless device."""
        if not self._xbee_manager:
            return None
        return self._xbee_manager.get_transport(node_id)

    async def destroy_wireless_transport(self, node_id: str) -> None:
        """Destroy transport for a wireless device."""
        if self._xbee_manager:
            await self._xbee_manager.destroy_transport(node_id)

    async def send_to_wireless_device(self, node_id: str, data: bytes) -> bool:
        """Send data to a wireless device."""
        if not self._xbee_manager:
            return False
        return await self._xbee_manager.send_data(node_id, data)
