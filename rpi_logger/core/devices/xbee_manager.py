"""
Unified XBee manager for wireless device discovery.

Combines functionality from:
- rpi_logger/modules/VOG/vog_core/xbee_manager.py
- rpi_logger/modules/DRT/drt_core/xbee_manager.py

Key difference: This manager handles BOTH wVOG and wDRT devices through
a single coordinator, using the higher baudrate (921600) to support wDRT.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, Awaitable, Set, Any
from enum import Enum

import serial.tools.list_ports

from rpi_logger.core.logging_utils import get_module_logger
from .device_registry import (
    DeviceType,
    DeviceFamily,
    XBEE_BAUDRATE,
    parse_wireless_node_id,
    get_spec,
    extract_device_number,
)

logger = get_module_logger("XBeeManager")

# XBee dongle identification
XBEE_VID = 0x0403
XBEE_PID = 0x6015

# Try to import digi-xbee library
try:
    from digi.xbee.devices import XBeeDevice, RemoteRaw802Device
    from digi.xbee.models.message import XBeeMessage
    from digi.xbee.exception import XBeeException, TransmitException
    XBEE_AVAILABLE = True
except ImportError:
    XBEE_AVAILABLE = False
    XBeeDevice = None
    RemoteRaw802Device = None
    XBeeMessage = None
    logger.warning("digi-xbee library not installed - XBee support disabled")


def is_xbee_dongle(port_info) -> bool:
    """Check if a port is an XBee dongle."""
    return port_info.vid == XBEE_VID and port_info.pid == XBEE_PID


@dataclass
class WirelessDevice:
    """Represents a discovered wireless device."""
    node_id: str                 # e.g., "wVOG_01" or "wDRT_02"
    device_type: DeviceType
    family: DeviceFamily
    address_64bit: str
    device_number: Optional[int] = None
    battery_percent: Optional[int] = None  # Reserved for future use


class XBeeManagerState(Enum):
    """XBee manager state."""
    DISABLED = "disabled"
    SCANNING = "scanning"
    CONNECTED = "connected"
    DISCOVERING = "discovering"


# Type aliases for callbacks
DongleCallback = Callable[[str], Awaitable[None]]
DongleDisconnectCallback = Callable[[], Awaitable[None]]
DeviceDiscoveredCallback = Callable[[WirelessDevice, Any], Awaitable[None]]  # device, remote_xbee
DeviceLostCallback = Callable[[str], Awaitable[None]]
StatusCallback = Callable[[str, str], Awaitable[None]]
DataReceivedCallback = Callable[[str, str], Awaitable[None]]  # node_id, data


class XBeeManager:
    """
    Manages XBee coordinator and wireless device discovery.

    Handles both wVOG and wDRT wireless devices through a single coordinator.
    Uses 921600 baudrate to support wDRT devices.
    """

    DEFAULT_SCAN_INTERVAL = 1.0
    DEFAULT_REDISCOVERY_INTERVAL = 30.0

    def __init__(
        self,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
        rediscovery_interval: float = DEFAULT_REDISCOVERY_INTERVAL,
    ):
        """
        Initialize the XBee manager.

        Args:
            scan_interval: Interval between dongle scans in seconds
            rediscovery_interval: Interval between network rediscovery in seconds
        """
        self._scan_interval = scan_interval
        self._rediscovery_interval = rediscovery_interval

        # Callbacks
        self.on_dongle_connected: Optional[DongleCallback] = None
        self.on_dongle_disconnected: Optional[DongleDisconnectCallback] = None
        self.on_device_discovered: Optional[DeviceDiscoveredCallback] = None
        self.on_device_lost: Optional[DeviceLostCallback] = None
        self.on_status_change: Optional[StatusCallback] = None
        self.on_data_received: Optional[DataReceivedCallback] = None

        # XBee state
        self._coordinator: Optional['XBeeDevice'] = None
        self._coordinator_port: Optional[str] = None
        self._remote_devices: Dict[str, 'RemoteRaw802Device'] = {}
        self._discovered_devices: Dict[str, WirelessDevice] = {}

        # State tracking
        self._state = XBeeManagerState.DISABLED
        self._running = False
        self._enabled = True  # Can be disabled for mutual exclusion
        self._scan_task: Optional[asyncio.Task] = None
        self._rediscovery_task: Optional[asyncio.Task] = None

        # Event loop reference for thread-safe callbacks
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Data handlers - maps node_id to callback that receives raw data
        # These are called directly from the XBee thread (must be thread-safe)
        self._data_handlers: Dict[str, Callable[[str], None]] = {}

    @property
    def is_connected(self) -> bool:
        """Check if coordinator is connected and open."""
        return (
            self._coordinator is not None and
            self._coordinator.is_open()
        )

    @property
    def is_enabled(self) -> bool:
        """Check if XBee is enabled (not disabled for mutual exclusion)."""
        return self._enabled

    @property
    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._running

    @property
    def state(self) -> XBeeManagerState:
        """Get current state."""
        return self._state

    @property
    def coordinator_port(self) -> Optional[str]:
        """Return the port of the connected coordinator, or None."""
        return self._coordinator_port if self.is_connected else None

    @property
    def discovered_devices(self) -> Dict[str, WirelessDevice]:
        """Return dict of discovered device node IDs to their info."""
        return dict(self._discovered_devices)

    def get_remote_device(self, node_id: str) -> Optional['RemoteRaw802Device']:
        """Get the raw XBee remote device for a node ID."""
        return self._remote_devices.get(node_id)

    @property
    def coordinator(self) -> Optional['XBeeDevice']:
        """Get the XBee coordinator device (read-only)."""
        return self._coordinator

    # =========================================================================
    # Data Handler Registration
    # =========================================================================

    def register_data_handler(self, node_id: str, handler: Callable[[str], None]) -> None:
        """
        Register a callback to receive data for a specific wireless device.

        The handler is called directly from the XBee library's thread when
        messages arrive. The handler MUST be thread-safe (e.g., use a Queue).

        Args:
            node_id: The device's node ID (e.g., "wVOG_01", "wDRT_02")
            handler: Callback function that receives data string
        """
        self._data_handlers[node_id] = handler
        logger.debug(f"Registered data handler for {node_id}")

    def unregister_data_handler(self, node_id: str) -> None:
        """
        Unregister the data handler for a wireless device.

        Args:
            node_id: The device's node ID
        """
        if node_id in self._data_handlers:
            del self._data_handlers[node_id]
            logger.debug(f"Unregistered data handler for {node_id}")

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the XBee manager and begin scanning for dongle."""
        if not XBEE_AVAILABLE:
            logger.warning("XBee library not available, cannot start")
            return

        if self._running:
            logger.warning("XBee manager already running")
            return

        if not self._enabled:
            logger.info("XBee manager disabled (mutual exclusion)")
            return

        self._running = True
        self._state = XBeeManagerState.SCANNING
        self._loop = asyncio.get_running_loop()

        logger.info("Starting unified XBee manager")

        # Start scanning for dongle
        self._scan_task = asyncio.create_task(self._scan_loop())

    async def stop(self) -> None:
        """Stop the XBee manager and close all connections."""
        self._running = False

        # Cancel scan task
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None

        # Cancel rediscovery task
        if self._rediscovery_task:
            self._rediscovery_task.cancel()
            try:
                await self._rediscovery_task
            except asyncio.CancelledError:
                pass
            self._rediscovery_task = None

        # Close coordinator
        await self._close_coordinator()

        self._state = XBeeManagerState.DISABLED
        logger.info("XBee manager stopped")

    async def disable(self) -> None:
        """
        Disable XBee (for mutual exclusion with USB w-devices).

        When a USB wVOG or wDRT is connected, XBee should be disabled
        to avoid conflicts.
        """
        self._enabled = False
        logger.info("XBee disabled (USB wireless device connected)")

        if self._running:
            await self.stop()

        if self.on_status_change:
            await self.on_status_change('disabled', 'USB wireless device connected')

    def enable(self) -> None:
        """
        Re-enable XBee (when USB wireless device disconnected).

        Note: This only sets the enabled flag. Call start() separately
        to begin scanning for the dongle.
        """
        self._enabled = True
        logger.info("XBee enabled")

    # =========================================================================
    # Dongle Scanning
    # =========================================================================

    async def _scan_loop(self) -> None:
        """Continuous scanning loop for XBee dongle."""
        while self._running and self._enabled:
            try:
                await self._scan_for_dongle()
                await asyncio.sleep(self._scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in XBee scan loop: {e}")

    async def _scan_for_dongle(self) -> None:
        """Scan for XBee dongle and initialize if found."""
        try:
            ports = await asyncio.to_thread(serial.tools.list_ports.comports)

            dongle_port = None
            for port_info in ports:
                if is_xbee_dongle(port_info):
                    dongle_port = port_info.device
                    break

            if dongle_port and not self.is_connected:
                # New dongle found
                await self._initialize_coordinator(dongle_port)
            elif not dongle_port and self.is_connected:
                # Dongle removed
                await self._close_coordinator()

        except Exception as e:
            logger.error(f"Error scanning for XBee dongle: {e}")

    async def _initialize_coordinator(self, port: str) -> None:
        """Initialize the XBee coordinator on the given port."""
        try:
            logger.info(f"Initializing XBee coordinator on {port} at {XBEE_BAUDRATE} baud")

            # Create and open coordinator
            self._coordinator = await asyncio.to_thread(
                XBeeDevice, port, XBEE_BAUDRATE
            )
            await asyncio.to_thread(self._coordinator.open)

            self._coordinator_port = port
            self._state = XBeeManagerState.CONNECTED

            # Set up message callback
            self._coordinator.add_data_received_callback(self._on_message_received)

            logger.info(f"XBee coordinator initialized on {port}")

            if self.on_dongle_connected:
                await self.on_dongle_connected(port)

            if self.on_status_change:
                await self.on_status_change('connected', port)

            # Start network discovery
            await self._start_network_discovery()

            # Start periodic rediscovery task
            if self._rediscovery_task is None or self._rediscovery_task.done():
                self._rediscovery_task = asyncio.create_task(
                    self._periodic_rediscovery_loop(),
                    name="xbee_rediscovery"
                )

        except Exception as e:
            logger.error(f"Failed to initialize XBee coordinator: {e}")
            self._coordinator = None
            self._coordinator_port = None
            self._state = XBeeManagerState.SCANNING

    async def _close_coordinator(self) -> None:
        """Close the XBee coordinator and clean up."""
        # Cancel rediscovery task
        if self._rediscovery_task:
            self._rediscovery_task.cancel()
            try:
                await self._rediscovery_task
            except asyncio.CancelledError:
                pass
            self._rediscovery_task = None

        # Notify about lost devices
        for node_id in list(self._discovered_devices.keys()):
            await self._handle_device_lost(node_id)

        # Close coordinator
        if self._coordinator:
            try:
                if self._coordinator.is_open():
                    await asyncio.to_thread(self._coordinator.close)
            except Exception as e:
                logger.error(f"Error closing XBee coordinator: {e}")
            finally:
                self._coordinator = None
                self._coordinator_port = None

        if self.on_dongle_disconnected:
            await self.on_dongle_disconnected()

        if self.on_status_change:
            await self.on_status_change('disconnected', '')

        self._state = XBeeManagerState.SCANNING if self._running else XBeeManagerState.DISABLED
        logger.info("XBee coordinator closed")

    # =========================================================================
    # Network Discovery
    # =========================================================================

    async def _start_network_discovery(self) -> None:
        """Start XBee network discovery to find remote devices."""
        if not self.is_connected:
            return

        try:
            logger.info("Starting XBee network discovery")
            self._state = XBeeManagerState.DISCOVERING

            network = self._coordinator.get_network()

            # Set discovery callback
            network.add_discovery_process_finished_callback(
                self._on_discovery_finished
            )

            # Start discovery (runs in background)
            await asyncio.to_thread(network.start_discovery_process)

        except Exception as e:
            logger.error(f"Error starting network discovery: {e}")
            self._state = XBeeManagerState.CONNECTED

    async def _periodic_rediscovery_loop(self) -> None:
        """Periodically trigger network rediscovery to find new devices."""
        logger.info(
            f"Starting periodic network rediscovery "
            f"(interval: {self._rediscovery_interval}s)"
        )

        while self._running and self._enabled and self.is_connected:
            try:
                await asyncio.sleep(self._rediscovery_interval)

                if not self.is_connected:
                    break

                logger.debug("Running periodic network rediscovery")
                await self._start_network_discovery()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic rediscovery: {e}")

        logger.debug("Periodic rediscovery loop ended")

    def _on_discovery_finished(self, status: Any) -> None:
        """
        Callback when network discovery completes.

        Called from XBee library's thread - schedules processing on main loop.
        """
        if not self.is_connected:
            return

        try:
            network = self._coordinator.get_network()
            devices = network.get_devices()

            logger.info(f"Network discovery found {len(devices)} device(s)")

            loop = self._loop
            if loop is None or not loop.is_running():
                logger.error("No running event loop for discovery callback")
                return

            for device in devices:
                def schedule_discovery(d=device):
                    if loop.is_running():
                        loop.create_task(self._handle_device_discovered(d))

                loop.call_soon_threadsafe(schedule_discovery)

            # Update state back to connected
            self._state = XBeeManagerState.CONNECTED

        except Exception as e:
            logger.error(f"Error processing discovery results: {e}")

    async def _handle_device_discovered(
        self,
        remote_device: 'RemoteRaw802Device'
    ) -> None:
        """Handle a newly discovered XBee device."""
        try:
            node_id = remote_device.get_node_id()
            if not node_id:
                logger.warning("Discovered device has no node ID")
                return

            # Parse node ID to determine device type (wVOG or wDRT)
            device_type = parse_wireless_node_id(node_id)
            if device_type is None:
                logger.debug(f"Ignoring device with unrecognized node ID: {node_id}")
                return

            # Skip if already known
            if node_id in self._discovered_devices:
                return

            spec = get_spec(device_type)
            address = str(remote_device.get_64bit_addr())
            device_number = extract_device_number(node_id)

            logger.info(f"Discovered wireless device: {node_id} ({device_type.value})")

            # Store device info
            device = WirelessDevice(
                node_id=node_id,
                device_type=device_type,
                family=spec.family,
                address_64bit=address,
                device_number=device_number,
            )

            self._discovered_devices[node_id] = device
            self._remote_devices[node_id] = remote_device

            # Notify callback
            if self.on_device_discovered:
                await self.on_device_discovered(device, remote_device)

        except Exception as e:
            logger.error(f"Error handling discovered device: {e}")

    async def _handle_device_lost(self, node_id: str) -> None:
        """Handle a lost XBee device."""
        # Unregister data handler first
        self.unregister_data_handler(node_id)

        device = self._discovered_devices.pop(node_id, None)
        self._remote_devices.pop(node_id, None)

        if device:
            logger.info(f"Lost wireless device: {node_id}")

            if self.on_device_lost:
                await self.on_device_lost(node_id)

    # =========================================================================
    # Message Handling
    # =========================================================================

    def _on_message_received(self, message: 'XBeeMessage') -> None:
        """
        Callback for received XBee messages.

        Called from XBee library's thread. Routes messages to registered
        handlers (synchronously, for thread-safe queue buffering) and
        optionally to the async on_data_received callback.
        """
        try:
            remote = message.remote_device
            node_id = remote.get_node_id() if remote else None

            if not node_id:
                logger.debug("Received message from unknown device (no node ID)")
                return

            # Decode data
            data = message.data.decode('utf-8', errors='replace')
            logger.debug(f"XBee received from {node_id}: '{data.strip()}'")

            # Route to registered handler (direct call - handler must be thread-safe)
            handler = self._data_handlers.get(node_id)
            if handler:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"Error in data handler for {node_id}: {e}")
            else:
                logger.debug(f"No handler registered for {node_id}, message dropped")

            # Also route to async callback if set (for legacy/monitoring purposes)
            if self.on_data_received and self._loop:
                def schedule_callback(n=node_id, d=data):
                    if self._loop.is_running():
                        self._loop.create_task(self.on_data_received(n, d))
                self._loop.call_soon_threadsafe(schedule_callback)

        except Exception as e:
            logger.error(f"Error handling XBee message: {e}")

    # =========================================================================
    # Public Methods
    # =========================================================================

    async def trigger_rediscovery(self) -> None:
        """Manually trigger network rediscovery."""
        if self.is_connected:
            await self._start_network_discovery()

    async def send_to_device(self, node_id: str, data: bytes) -> bool:
        """
        Send data to a wireless device.

        Args:
            node_id: Target device node ID
            data: Data to send

        Returns:
            True if send was successful
        """
        if not self.is_connected:
            return False

        remote = self._remote_devices.get(node_id)
        if not remote:
            logger.error(f"Unknown device: {node_id}")
            return False

        try:
            await asyncio.to_thread(
                self._coordinator.send_data, remote, data
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send to {node_id}: {e}")
            return False

    def get_devices_by_family(self, family: DeviceFamily) -> list[WirelessDevice]:
        """Get all discovered devices of a specific family."""
        return [
            d for d in self._discovered_devices.values()
            if d.family == family
        ]

    def get_devices_by_type(self, device_type: DeviceType) -> list[WirelessDevice]:
        """Get all discovered devices of a specific type."""
        return [
            d for d in self._discovered_devices.values()
            if d.device_type == device_type
        ]
