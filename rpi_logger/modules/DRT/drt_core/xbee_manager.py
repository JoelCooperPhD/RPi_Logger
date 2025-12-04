"""
XBee Connection Manager

Manages XBee dongle detection, network discovery, and wireless device connections.
Handles communication with wDRT devices over XBee 802.15.4 network.
"""

import asyncio
import re
from typing import Dict, Optional, Callable, Awaitable, Set, Any
import logging

import serial.tools.list_ports

from .device_types import XBEE_DONGLE, is_xbee_dongle
from .transports import XBeeTransport
from .utils.rtc import format_rtc_sync

logger = logging.getLogger(__name__)

# Try to import digi-xbee library
try:
    from digi.xbee.devices import XBeeDevice, RemoteRaw802Device
    from digi.xbee.models.message import XBeeMessage
    from digi.xbee.exception import XBeeException, TransmitException
    XBEE_AVAILABLE = True
except ImportError:
    XBEE_AVAILABLE = False
    logger.warning("digi-xbee library not installed - XBee support disabled")

# Type aliases
DeviceDiscoveredCallback = Callable[[str, 'XBeeTransport'], Awaitable[None]]
DeviceLostCallback = Callable[[str], Awaitable[None]]
StatusCallback = Callable[[str, str], Awaitable[None]]


class XBeeManager:
    """
    Manages XBee wireless network for wDRT devices.

    Features:
    - XBee dongle detection and initialization
    - Network discovery for remote wDRT devices
    - Message routing between coordinator and remote devices
    - Automatic RTC synchronization on device discovery
    - Mutual exclusion with USB wDRT (disabled when USB wDRT connected)
    """

    # Default interval for periodic network rediscovery (in seconds)
    DEFAULT_REDISCOVERY_INTERVAL = 30.0

    def __init__(
        self,
        scan_interval: float = 1.0,
        rediscovery_interval: float = DEFAULT_REDISCOVERY_INTERVAL
    ):
        """
        Initialize the XBee manager.

        Args:
            scan_interval: Interval between dongle scans in seconds
            rediscovery_interval: Interval between network rediscovery scans in seconds
        """
        if not XBEE_AVAILABLE:
            raise RuntimeError("digi-xbee library not installed")

        self.scan_interval = scan_interval
        self.rediscovery_interval = rediscovery_interval

        # Callbacks
        self.on_device_discovered: Optional[DeviceDiscoveredCallback] = None
        self.on_device_lost: Optional[DeviceLostCallback] = None
        self.on_status_change: Optional[StatusCallback] = None

        # XBee state
        self._coordinator: Optional[XBeeDevice] = None
        self._coordinator_port: Optional[str] = None
        self._remote_devices: Dict[str, RemoteRaw802Device] = {}
        self._transports: Dict[str, XBeeTransport] = {}

        # State tracking
        self._running = False
        self._enabled = True  # Can be disabled for mutual exclusion
        self._scan_task: Optional[asyncio.Task] = None
        self._rediscovery_task: Optional[asyncio.Task] = None
        self._known_ports: Set[str] = set()

        # Event loop reference - set during start() and used for thread-safe callbacks
        # We also try to get it at init time for early callbacks
        try:
            self._loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None  # No running loop yet, will be set in start()

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
    def coordinator_port(self) -> Optional[str]:
        """Return the port of the connected coordinator, or None if not connected."""
        return self._coordinator_port if self.is_connected else None

    @property
    def discovered_devices(self) -> Dict[str, XBeeTransport]:
        """Return dict of discovered device node IDs to their transports."""
        return self._transports.copy()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the XBee manager and begin scanning for dongle."""
        if self._running:
            logger.warning("XBee manager already running")
            return

        if not self._enabled:
            logger.info("XBee manager disabled (mutual exclusion)")
            return

        self._running = True
        self._loop = asyncio.get_running_loop()  # Store event loop reference
        logger.info("Starting XBee manager")

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

        logger.info("XBee manager stopped")

    async def disable(self) -> None:
        """
        Disable XBee (for mutual exclusion with USB wDRT).

        When a USB wDRT is connected, XBee should be disabled.
        This properly stops the manager and cleans up state.
        """
        self._enabled = False
        logger.info("XBee disabled (USB wDRT connected)")

        # Properly stop if running
        if self._running:
            await self.stop()

        if self.on_status_change:
            await self.on_status_change('disabled', 'USB wDRT connected')

    def enable(self) -> None:
        """
        Re-enable XBee (when USB wDRT disconnected).

        Note: This only sets the enabled flag. Call start() separately
        to begin scanning for the dongle.
        """
        self._enabled = True
        logger.info("XBee enabled")

        if self.on_status_change:
            asyncio.create_task(
                self.on_status_change('enabled', '')
            )

    # =========================================================================
    # Dongle Scanning
    # =========================================================================

    async def _scan_loop(self) -> None:
        """Continuous scanning loop for XBee dongle."""
        while self._running and self._enabled:
            try:
                await self._scan_for_dongle()
                await asyncio.sleep(self.scan_interval)
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
        """
        Initialize the XBee coordinator on the given port.

        Args:
            port: Serial port of the XBee dongle
        """
        try:
            logger.info(f"Initializing XBee coordinator on {port}")

            # Create and open coordinator
            self._coordinator = await asyncio.to_thread(
                XBeeDevice, port, XBEE_DONGLE.baudrate
            )
            await asyncio.to_thread(self._coordinator.open)

            self._coordinator_port = port

            # Set up message callback
            self._coordinator.add_data_received_callback(self._on_message_received)

            logger.info(f"XBee coordinator initialized on {port}")

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
        for node_id in list(self._transports.keys()):
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

        if self.on_status_change:
            await self.on_status_change('disconnected', '')

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

            network = self._coordinator.get_network()

            # Set discovery callback
            network.add_discovery_process_finished_callback(
                self._on_discovery_finished
            )

            # Start discovery (runs in background)
            await asyncio.to_thread(network.start_discovery_process)

        except Exception as e:
            logger.error(f"Error starting network discovery: {e}")

    async def _periodic_rediscovery_loop(self) -> None:
        """
        Periodically trigger network rediscovery to find new devices.

        This catches devices that power on after the initial discovery,
        or devices that temporarily went out of range and came back.
        """
        logger.info(
            f"Starting periodic network rediscovery "
            f"(interval: {self.rediscovery_interval}s)"
        )

        while self._running and self._enabled and self.is_connected:
            try:
                await asyncio.sleep(self.rediscovery_interval)

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

        This is called from the XBee library's thread, so we need to
        schedule processing on the main event loop.

        Args:
            status: Discovery status
        """
        if not self.is_connected:
            return

        try:
            network = self._coordinator.get_network()
            devices = network.get_devices()

            logger.info(f"Network discovery found {len(devices)} device(s)")

            # Schedule processing on the main event loop
            # This callback runs in XBee's thread, not the asyncio thread
            loop = self._loop
            if loop is None or not loop.is_running():
                logger.error(
                    "No running event loop available for discovery callback. "
                    "Devices will be discovered on next network scan."
                )
                return

            for device in devices:
                # Capture device in closure properly
                def schedule_discovery(d=device):
                    if loop.is_running():
                        loop.create_task(self._handle_device_discovered(d))

                loop.call_soon_threadsafe(schedule_discovery)

        except Exception as e:
            logger.error(f"Error processing discovery results: {e}")

    async def _handle_device_discovered(
        self,
        remote_device: 'RemoteRaw802Device'
    ) -> None:
        """
        Handle a newly discovered XBee device.

        Args:
            remote_device: The discovered remote device
        """
        try:
            node_id = remote_device.get_node_id()
            if not node_id:
                logger.warning("Discovered device has no node ID")
                return

            # Parse node ID to check if it's a wDRT
            # Expected format: "wDRT_XX" where XX is a number (e.g., "wDRT_01", "wDRT 02")
            # Using anchored regex to ensure exact match
            match = re.match(r'^([a-zA-Z]+)[_\s]*(\d+)$', node_id.strip())
            if not match:
                logger.debug(f"Ignoring device with unrecognized node ID format: {node_id}")
                return

            device_type, device_num = match.groups()
            if device_type.lower() != 'wdrt':
                logger.debug(f"Ignoring non-wDRT device: {node_id} (type: {device_type})")
                return

            # Skip if already known
            if node_id in self._transports:
                return

            logger.info(f"Discovered wDRT device: {node_id}")

            # Store remote device
            self._remote_devices[node_id] = remote_device

            # Create transport
            transport = XBeeTransport(
                remote_device=remote_device,
                coordinator=self._coordinator,
                node_id=node_id
            )
            await transport.connect()
            self._transports[node_id] = transport

            # Sync RTC
            await self._sync_device_rtc(node_id)

            # Notify callback
            if self.on_device_discovered:
                await self.on_device_discovered(node_id, transport)

        except Exception as e:
            logger.error(f"Error handling discovered device: {e}")

    async def _handle_device_lost(self, node_id: str) -> None:
        """
        Handle a lost XBee device.

        Args:
            node_id: The node ID of the lost device
        """
        transport = self._transports.pop(node_id, None)
        self._remote_devices.pop(node_id, None)

        if transport:
            await transport.disconnect()
            logger.info(f"Lost wDRT device: {node_id}")

            if self.on_device_lost:
                await self.on_device_lost(node_id)

    # =========================================================================
    # Message Handling
    # =========================================================================

    def _on_message_received(self, message: 'XBeeMessage') -> None:
        """
        Callback for received XBee messages.

        Routes messages to the appropriate transport.

        Args:
            message: The received XBee message
        """
        try:
            # Get sender node ID
            remote = message.remote_device
            node_id = remote.get_node_id() if remote else None

            if not node_id:
                logger.debug("Received message from unknown device")
                return

            # Route to transport
            transport = self._transports.get(node_id)
            if transport:
                data = message.data.decode('utf-8')
                logger.debug(f"XBee manager received from {node_id}: '{data.strip()}'")
                transport.handle_received_data(data)
            else:
                logger.debug(f"Message from untracked device: {node_id}")

        except Exception as e:
            logger.error(f"Error handling XBee message: {e}")

    # =========================================================================
    # Device Commands
    # =========================================================================

    async def _sync_device_rtc(self, node_id: str) -> bool:
        """
        Synchronize RTC on a remote device.

        Args:
            node_id: The device node ID

        Returns:
            True if sync was successful
        """
        transport = self._transports.get(node_id)
        if not transport:
            return False

        rtc_string = format_rtc_sync()
        command = f"set_rtc>{rtc_string}"

        logger.info(f"Syncing RTC for {node_id}")
        return await transport.write_line(command, '\n')

    async def rescan_network(self) -> None:
        """
        Trigger a new network discovery.

        Clears existing devices and rediscovers.
        """
        if not self.is_connected:
            logger.warning("Cannot rescan: not connected")
            return

        # Clear existing devices
        for node_id in list(self._transports.keys()):
            await self._handle_device_lost(node_id)

        # Start new discovery
        await self._start_network_discovery()

    def get_transport(self, node_id: str) -> Optional[XBeeTransport]:
        """
        Get the transport for a specific device.

        Args:
            node_id: The device node ID

        Returns:
            Transport instance, or None if not found
        """
        return self._transports.get(node_id)
