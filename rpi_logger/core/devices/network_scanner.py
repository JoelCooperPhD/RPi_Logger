"""
Network device scanner using mDNS/Zeroconf.

Discovers Pupil Labs eye trackers (Neon, Invisible) on the local network.
Follows the same pattern as USBScanner for consistency.
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Awaitable

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("NetworkScanner")

# Try to import zeroconf - it's optional
try:
    from zeroconf import ServiceStateChange, Zeroconf
    from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False
    logger.warning("zeroconf not available - network device discovery disabled")


@dataclass
class DiscoveredNetworkDevice:
    """Represents a discovered network device."""
    device_id: str           # Unique ID based on hardware ID or IP
    address: str             # IP address
    port: int                # API port (typically 8080)
    name: str                # Friendly device name from mDNS
    hardware_id: str         # Hardware ID from mDNS service name
    full_service_name: str   # Full mDNS service name for debugging


# Type alias for callbacks
NetworkDeviceFoundCallback = Callable[[DiscoveredNetworkDevice], Awaitable[None]]
NetworkDeviceLostCallback = Callable[[str], Awaitable[None]]  # device_id


class NetworkScanner:
    """
    Continuously scans for network devices using mDNS.

    Currently discovers Pupil Labs eye trackers that advertise via mDNS.
    Service pattern: "PI monitor:<device_name>:<hardware_id>._http._tcp.local."

    Usage:
        scanner = NetworkScanner(
            on_device_found=handle_found,
            on_device_lost=handle_lost,
        )
        await scanner.start()
        # ... later ...
        await scanner.stop()
    """

    # Pupil Labs uses _http._tcp.local. for service discovery
    SERVICE_TYPE = "_http._tcp.local."

    # Pattern to match Pupil Labs devices: "PI monitor:<name>:<hardware_id>"
    # Example: "PI monitor:Neon Lab-1:abc123def456"
    PUPIL_LABS_PATTERN = re.compile(r"^PI monitor:([^:]+):([^.]+)")

    def __init__(
        self,
        on_device_found: Optional[NetworkDeviceFoundCallback] = None,
        on_device_lost: Optional[NetworkDeviceLostCallback] = None,
    ):
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost

        self._known_devices: Dict[str, DiscoveredNetworkDevice] = {}
        self._zeroconf: Optional[AsyncZeroconf] = None
        self._browser: Optional[AsyncServiceBrowser] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def devices(self) -> Dict[str, DiscoveredNetworkDevice]:
        """Get currently known devices (device_id -> device)."""
        return dict(self._known_devices)

    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running

    async def start(self) -> None:
        """Start mDNS service discovery."""
        if self._running:
            return

        if not ZEROCONF_AVAILABLE:
            logger.warning("Cannot start network scanner - zeroconf not available")
            return

        self._running = True
        self._loop = asyncio.get_running_loop()

        try:
            self._zeroconf = AsyncZeroconf()
            self._browser = AsyncServiceBrowser(
                self._zeroconf.zeroconf,
                self.SERVICE_TYPE,
                handlers=[self._on_service_state_change]
            )
            logger.info("Network scanner started - listening for mDNS services")
        except Exception as e:
            logger.error(f"Failed to start network scanner: {e}")
            self._running = False
            raise

    async def stop(self) -> None:
        """Stop mDNS service discovery."""
        if not self._running:
            return

        self._running = False

        try:
            if self._browser:
                await self._browser.async_cancel()
                self._browser = None

            if self._zeroconf:
                await self._zeroconf.async_close()
                self._zeroconf = None
        except Exception as e:
            logger.error(f"Error stopping network scanner: {e}")

        # Notify about lost devices
        for device_id in list(self._known_devices.keys()):
            await self._handle_device_lost(device_id)

        self._known_devices.clear()
        logger.info("Network scanner stopped")

    async def force_scan(self) -> None:
        """Force a re-discovery of network devices.

        Note: mDNS is event-driven, so this just logs a message.
        Devices announce themselves; we can't actively probe.
        """
        if self._running:
            logger.debug("Network scanner uses mDNS events - no manual scan needed")

    async def reannounce_devices(self) -> None:
        """Re-emit discovery events for all known devices."""
        logger.debug(f"Re-announcing {len(self._known_devices)} network devices")
        for device in self._known_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(device)
                except Exception as e:
                    logger.error(f"Error re-announcing network device: {e}")

    def _on_service_state_change(self, **kwargs) -> None:
        """Handle mDNS service state changes.

        This is called from the zeroconf thread, so we schedule
        the actual handling on the asyncio event loop.

        Note: zeroconf >= 0.132 changed to keyword-only arguments.
        Using **kwargs for compatibility with both old and new versions.
        """
        if self._loop is None:
            return

        zeroconf_instance = kwargs.get("zeroconf")
        service_type = kwargs.get("service_type", "")
        name = kwargs.get("name", "")
        state_change = kwargs.get("state_change")

        if state_change == ServiceStateChange.Added:
            asyncio.run_coroutine_threadsafe(
                self._handle_service_added(zeroconf_instance, service_type, name),
                self._loop
            )
        elif state_change == ServiceStateChange.Removed:
            asyncio.run_coroutine_threadsafe(
                self._handle_service_removed(name),
                self._loop
            )

    async def _handle_service_added(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
    ) -> None:
        """Handle a new mDNS service being discovered."""
        # Check if this is a Pupil Labs device
        match = self.PUPIL_LABS_PATTERN.match(name)
        if not match:
            return  # Not a Pupil Labs device

        device_name = match.group(1)
        hardware_id = match.group(2)

        # Get service info for IP and port
        try:
            info = await asyncio.to_thread(
                zeroconf.get_service_info,
                service_type,
                name,
                timeout=3000  # 3 seconds
            )
        except Exception as e:
            logger.warning(f"Failed to get service info for {name}: {e}")
            return

        if info is None:
            logger.warning(f"No service info available for {name}")
            return

        # Extract address and port
        addresses = info.parsed_addresses()
        if not addresses:
            logger.warning(f"No addresses found for {name}")
            return

        address = addresses[0]  # Use first address
        port = info.port or 8080  # Default to 8080 if not specified

        # Create unique device ID based on hardware ID
        device_id = f"eyetracker_{hardware_id}"

        # Check if already known
        if device_id in self._known_devices:
            # Update address/port in case they changed
            existing = self._known_devices[device_id]
            if existing.address != address or existing.port != port:
                logger.info(
                    f"Eye tracker {device_name} address changed: "
                    f"{existing.address}:{existing.port} -> {address}:{port}"
                )
                existing = DiscoveredNetworkDevice(
                    device_id=device_id,
                    address=address,
                    port=port,
                    name=device_name,
                    hardware_id=hardware_id,
                    full_service_name=name,
                )
                self._known_devices[device_id] = existing
            return

        # New device discovered
        device = DiscoveredNetworkDevice(
            device_id=device_id,
            address=address,
            port=port,
            name=device_name,
            hardware_id=hardware_id,
            full_service_name=name,
        )

        self._known_devices[device_id] = device
        logger.info(f"Eye tracker discovered: {device_name} at {address}:{port}")

        if self._on_device_found:
            try:
                await self._on_device_found(device)
            except Exception as e:
                logger.error(f"Error in device found callback: {e}")

    async def _handle_service_removed(self, name: str) -> None:
        """Handle an mDNS service being removed."""
        # Check if this is a Pupil Labs device
        match = self.PUPIL_LABS_PATTERN.match(name)
        if not match:
            return

        hardware_id = match.group(2)
        device_id = f"eyetracker_{hardware_id}"

        await self._handle_device_lost(device_id)

    async def _handle_device_lost(self, device_id: str) -> None:
        """Handle a device being lost."""
        device = self._known_devices.pop(device_id, None)
        if device:
            logger.info(f"Eye tracker lost: {device.name} ({device.address})")

            if self._on_device_lost:
                try:
                    await self._on_device_lost(device_id)
                except Exception as e:
                    logger.error(f"Error in device lost callback: {e}")

    def get_device(self, device_id: str) -> Optional[DiscoveredNetworkDevice]:
        """Get a specific device by ID."""
        return self._known_devices.get(device_id)
