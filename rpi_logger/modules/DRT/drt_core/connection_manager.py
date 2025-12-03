"""
DRT Connection Manager

Manages USB and XBee device detection and connections for all DRT device types.
Provides a unified interface for device discovery and handler creation.
"""

import asyncio
from pathlib import Path
from typing import Dict, Optional, Callable, Awaitable, Set, Any
import logging

import serial.tools.list_ports

from .device_types import (
    DRTDeviceType,
    DeviceSpec,
    DEVICE_REGISTRY,
    XBEE_DONGLE,
    identify_device_type,
    is_xbee_dongle,
    get_device_spec,
)
from .transports import USBTransport, XBeeTransport
from .handlers import BaseDRTHandler, SDRTHandler, WDRTUSBHandler, WDRTWirelessHandler

logger = logging.getLogger(__name__)

# Check if XBee support is available
try:
    from .xbee_manager import XBeeManager, XBEE_AVAILABLE
except ImportError:
    XBEE_AVAILABLE = False
    XBeeManager = None

# Type alias for device event callbacks
DeviceCallback = Callable[[str, DRTDeviceType, BaseDRTHandler], Awaitable[None]]
DisconnectCallback = Callable[[str, DRTDeviceType], Awaitable[None]]


class ConnectionManager:
    """
    Manages USB and XBee device detection and connections for DRT devices.

    Features:
    - Continuous scanning for multiple DRT device types
    - Automatic handler creation based on device type
    - Hot-plug detection (connect/disconnect)
    - XBee network management for wireless wDRT devices
    - Mutual exclusion between USB wDRT and XBee
    """

    def __init__(
        self,
        output_dir: Path,
        scan_interval: float = 1.0,
        enable_xbee: bool = True
    ):
        """
        Initialize the connection manager.

        Args:
            output_dir: Default output directory for data logging
            scan_interval: Interval between port scans in seconds
            enable_xbee: Whether to enable XBee wireless support
        """
        self.output_dir = output_dir
        self.scan_interval = scan_interval

        # Callbacks
        self.on_device_connected: Optional[DeviceCallback] = None
        self.on_device_disconnected: Optional[DisconnectCallback] = None
        self.on_xbee_status_change: Optional[Callable[[str, str], Awaitable[None]]] = None

        # State tracking
        self._handlers: Dict[str, BaseDRTHandler] = {}
        self._device_types: Dict[str, DRTDeviceType] = {}
        self._known_ports: Set[str] = set()
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        self._xbee_start_task: Optional[asyncio.Task] = None  # Track XBee start task

        # XBee manager (if available and enabled)
        self._xbee_manager: Optional['XBeeManager'] = None
        self._xbee_enabled = enable_xbee and XBEE_AVAILABLE
        if self._xbee_enabled and XBeeManager:
            self._xbee_manager = XBeeManager(scan_interval=scan_interval)
            self._xbee_manager.on_device_discovered = self._on_xbee_device_discovered
            self._xbee_manager.on_device_lost = self._on_xbee_device_lost
            self._xbee_manager.on_status_change = self._on_xbee_status_change

    @property
    def handlers(self) -> Dict[str, BaseDRTHandler]:
        """Return all active handlers."""
        return self._handlers.copy()

    @property
    def connected_devices(self) -> Dict[str, DRTDeviceType]:
        """Return dict of connected device ports to their types."""
        return self._device_types.copy()

    @property
    def has_usb_wdrt(self) -> bool:
        """Check if any USB wDRT is connected."""
        return DRTDeviceType.WDRT_USB in self._device_types.values()

    @property
    def xbee_connected(self) -> bool:
        """Check if XBee dongle is connected."""
        return self._xbee_manager is not None and self._xbee_manager.is_connected

    @property
    def xbee_enabled(self) -> bool:
        """Check if XBee support is enabled."""
        return self._xbee_enabled

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the connection manager and begin scanning for devices."""
        if self._running:
            logger.warning("Connection manager already running")
            return

        self._running = True
        logger.info("Starting DRT connection manager")

        # Perform initial scan
        await self._scan_ports()

        # Start continuous scanning
        self._scan_task = asyncio.create_task(self._scan_loop())

        # Start XBee manager if enabled and no USB wDRT connected
        if self._xbee_manager and not self.has_usb_wdrt:
            await self._xbee_manager.start()

    async def stop(self) -> None:
        """Stop the connection manager and disconnect all devices."""
        self._running = False

        # Cancel scan task
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None

        # Stop XBee manager
        if self._xbee_manager:
            await self._xbee_manager.stop()

        # Disconnect all devices
        await self._disconnect_all()

        logger.info("DRT connection manager stopped")

    async def _disconnect_all(self) -> None:
        """Disconnect all connected devices."""
        for port in list(self._handlers.keys()):
            await self._handle_disconnect(port)

    # =========================================================================
    # Port Scanning
    # =========================================================================

    async def _scan_loop(self) -> None:
        """Continuous port scanning loop."""
        while self._running:
            try:
                await asyncio.sleep(self.scan_interval)
                await self._scan_ports()
                await self._check_handler_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")

    async def _scan_ports(self) -> None:
        """Scan for DRT devices and handle connect/disconnect events."""
        try:
            # Get current ports
            ports = await asyncio.to_thread(serial.tools.list_ports.comports)
            current_ports: Set[str] = set()

            for port_info in ports:
                port = port_info.device
                current_ports.add(port)

                # Skip if already known
                if port in self._known_ports:
                    continue

                # Skip XBee dongle - handled by XBeeManager
                if is_xbee_dongle(port_info):
                    continue

                # Check for DRT devices
                device_type = identify_device_type(port_info)
                if device_type:
                    await self._handle_connect(port, device_type, port_info)

            # Check for disconnections
            disconnected = self._known_ports - current_ports
            for port in disconnected:
                if port in self._handlers:
                    await self._handle_disconnect(port)

            self._known_ports = current_ports

        except Exception as e:
            logger.error(f"Error scanning ports: {e}")

    async def _check_handler_health(self) -> None:
        """
        Check health of all active handlers.

        Disconnects handlers that have triggered their circuit breaker
        or are otherwise in a bad state.
        """
        unhealthy_devices = []

        for device_id, handler in self._handlers.items():
            # Check if circuit breaker has tripped
            if handler.circuit_breaker_tripped:
                logger.warning(
                    f"Handler for {device_id} has tripped circuit breaker, "
                    f"scheduling disconnect"
                )
                unhealthy_devices.append(device_id)
            # Check if handler stopped unexpectedly
            elif not handler.is_running and handler.is_connected:
                logger.warning(
                    f"Handler for {device_id} stopped unexpectedly, "
                    f"scheduling disconnect"
                )
                unhealthy_devices.append(device_id)

        # Disconnect unhealthy devices
        for device_id in unhealthy_devices:
            await self._handle_disconnect(device_id)

    # =========================================================================
    # Device Connection Handling
    # =========================================================================

    async def _handle_connect(
        self,
        port: str,
        device_type: DRTDeviceType,
        port_info: Any
    ) -> None:
        """
        Handle a new device connection.

        Args:
            port: Serial port path
            device_type: Type of DRT device
            port_info: Serial port info object
        """
        logger.info(f"Detected {device_type.value} on {port}")

        # Get device spec
        spec = get_device_spec(device_type)
        if not spec:
            logger.error(f"No spec found for device type {device_type}")
            return

        # Create transport
        transport = USBTransport(
            port=port,
            baudrate=spec.baudrate
        )

        # Connect transport
        if not await transport.connect():
            logger.error(f"Failed to connect to {port}")
            return

        # Create handler based on device type
        handler = self._create_handler(device_type, port, transport)
        if not handler:
            await transport.disconnect()
            logger.error(f"Failed to create handler for {device_type}")
            return

        # Start handler
        await handler.start()

        # Store handler and type
        self._handlers[port] = handler
        self._device_types[port] = device_type

        # Check mutual exclusion if wDRT USB connected
        if device_type == DRTDeviceType.WDRT_USB:
            await self._check_mutual_exclusion()

        # Notify callback
        if self.on_device_connected:
            await self.on_device_connected(port, device_type, handler)

    def _create_handler(
        self,
        device_type: DRTDeviceType,
        port: str,
        transport: USBTransport
    ) -> Optional[BaseDRTHandler]:
        """
        Create the appropriate handler for a device type.

        Args:
            device_type: Type of DRT device
            port: Serial port path
            transport: Connected transport

        Returns:
            Handler instance, or None if type not supported
        """
        if device_type == DRTDeviceType.SDRT:
            return SDRTHandler(
                device_id=port,
                output_dir=self.output_dir,
                transport=transport
            )
        elif device_type == DRTDeviceType.WDRT_USB:
            return WDRTUSBHandler(
                device_id=port,
                output_dir=self.output_dir,
                transport=transport
            )
        else:
            logger.warning(f"Unknown device type: {device_type}")
            return None

    async def _handle_disconnect(self, port: str) -> None:
        """
        Handle a device disconnection.

        Args:
            port: Serial port that was disconnected
        """
        handler = self._handlers.pop(port, None)
        device_type = self._device_types.pop(port, None)

        if handler:
            logger.info(f"Device disconnected: {port}")
            await handler.stop()
            if handler.transport:
                await handler.transport.disconnect()

            # Check mutual exclusion if wDRT USB disconnected
            if device_type == DRTDeviceType.WDRT_USB:
                await self._check_mutual_exclusion()

            # Notify callback
            if self.on_device_disconnected and device_type:
                await self.on_device_disconnected(port, device_type)

    # =========================================================================
    # XBee Integration
    # =========================================================================

    async def _on_xbee_device_discovered(
        self,
        node_id: str,
        transport: XBeeTransport
    ) -> None:
        """
        Handle a wireless wDRT device discovered via XBee.

        Args:
            node_id: XBee node ID (e.g., "wDRT_01")
            transport: XBee transport for the device
        """
        logger.info(f"Wireless wDRT discovered: {node_id}")

        # Create handler for wireless device
        handler = WDRTWirelessHandler(
            device_id=node_id,
            output_dir=self.output_dir,
            transport=transport
        )

        # Start handler
        await handler.start()

        # Store handler
        self._handlers[node_id] = handler
        self._device_types[node_id] = DRTDeviceType.WDRT_WIRELESS

        # Notify callback
        if self.on_device_connected:
            await self.on_device_connected(
                node_id,
                DRTDeviceType.WDRT_WIRELESS,
                handler
            )

    async def _on_xbee_device_lost(self, node_id: str) -> None:
        """
        Handle a wireless wDRT device being lost.

        Args:
            node_id: XBee node ID
        """
        handler = self._handlers.pop(node_id, None)
        device_type = self._device_types.pop(node_id, None)

        if handler:
            logger.info(f"Wireless wDRT lost: {node_id}")
            await handler.stop()

            if self.on_device_disconnected and device_type:
                await self.on_device_disconnected(node_id, device_type)

    async def _on_xbee_status_change(self, status: str, detail: str) -> None:
        """
        Handle XBee status changes.

        Args:
            status: Status string ('connected', 'disconnected', 'disabled', 'enabled')
            detail: Additional detail (e.g., port name)
        """
        logger.info(f"XBee status: {status} {detail}")

        if self.on_xbee_status_change:
            await self.on_xbee_status_change(status, detail)

    async def _check_mutual_exclusion(self) -> None:
        """
        Check and enforce mutual exclusion between USB wDRT and XBee.

        When USB wDRT is connected, XBee should be disabled.
        When USB wDRT is disconnected, XBee can be re-enabled.
        """
        if not self._xbee_manager:
            return

        if self.has_usb_wdrt:
            # Disable XBee when USB wDRT is connected
            if self._xbee_manager.is_enabled:
                # Cancel any pending start task
                if self._xbee_start_task and not self._xbee_start_task.done():
                    self._xbee_start_task.cancel()
                    try:
                        await self._xbee_start_task
                    except asyncio.CancelledError:
                        pass
                    self._xbee_start_task = None

                await self._xbee_manager.disable()
        else:
            # Re-enable XBee when no USB wDRT
            if not self._xbee_manager.is_enabled:
                self._xbee_manager.enable()

                # Cancel any existing start task before creating new one
                if self._xbee_start_task and not self._xbee_start_task.done():
                    self._xbee_start_task.cancel()
                    try:
                        await self._xbee_start_task
                    except asyncio.CancelledError:
                        pass

                self._xbee_start_task = asyncio.create_task(
                    self._xbee_manager.start(),
                    name="xbee_start"
                )

    async def rescan_xbee_network(self) -> None:
        """Trigger a rescan of the XBee network for wireless devices."""
        if self._xbee_manager and self._xbee_manager.is_connected:
            await self._xbee_manager.rescan_network()

    # =========================================================================
    # Handler Access
    # =========================================================================

    def get_handler(self, port: str) -> Optional[BaseDRTHandler]:
        """
        Get the handler for a specific port.

        Args:
            port: Serial port path

        Returns:
            Handler instance, or None if not connected
        """
        return self._handlers.get(port)

    def get_handlers_by_type(
        self,
        device_type: DRTDeviceType
    ) -> Dict[str, BaseDRTHandler]:
        """
        Get all handlers of a specific device type.

        Args:
            device_type: Type of devices to get

        Returns:
            Dict of port to handler for matching devices
        """
        return {
            port: handler
            for port, handler in self._handlers.items()
            if self._device_types.get(port) == device_type
        }

    def update_output_dir(self, output_dir: Path) -> None:
        """
        Update the output directory for all handlers.

        Args:
            output_dir: New output directory path
        """
        self.output_dir = output_dir
        for handler in self._handlers.values():
            handler.update_output_dir(output_dir)
