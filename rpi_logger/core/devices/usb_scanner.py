"""
USB port scanner for device discovery.

Replaces scanning in:
- rpi_logger/modules/VOG/vog_core/connection_manager.py
- rpi_logger/modules/DRT/drt_core/connection_manager.py
"""

import asyncio
import sys
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Set, Awaitable
import serial.tools.list_ports

from rpi_logger.core.logging_utils import get_module_logger
from .types import DeviceType
from .device_registry import DeviceSpec, identify_usb_device

logger = get_module_logger("USBScanner")


@dataclass
class DiscoveredUSBDevice:
    """Represents a discovered USB device."""
    port: str                    # e.g., "/dev/ttyACM0"
    device_type: DeviceType
    spec: DeviceSpec
    serial_number: Optional[str]
    description: str             # e.g., "sVOG" or port description


# Type alias for callbacks
DeviceFoundCallback = Callable[[DiscoveredUSBDevice], Awaitable[None]]
DeviceLostCallback = Callable[[str], Awaitable[None]]


class USBScanner:
    """
    Continuously scans USB ports for supported devices.

    Usage:
        scanner = USBScanner(
            on_device_found=handle_found,
            on_device_lost=handle_lost,
        )
        await scanner.start()
        # ... later ...
        await scanner.stop()
    """

    DEFAULT_SCAN_INTERVAL = 1.0

    def __init__(
        self,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
        on_device_found: Optional[DeviceFoundCallback] = None,
        on_device_lost: Optional[DeviceLostCallback] = None,
    ):
        self._scan_interval = scan_interval
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost

        self._known_devices: Dict[str, DiscoveredUSBDevice] = {}
        self._known_ports: Set[str] = set()
        self._scan_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def devices(self) -> Dict[str, DiscoveredUSBDevice]:
        """Get currently known devices (port -> device)."""
        return dict(self._known_devices)

    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running

    async def start(self) -> None:
        """Start the USB scanning loop."""
        if self._running:
            return
        self._running = True

        # Perform initial scan immediately
        await self._scan_ports()

        # Start continuous scanning
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("USB scanner started")

    async def stop(self) -> None:
        """Stop the USB scanning loop."""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None

        self._known_devices.clear()
        self._known_ports.clear()
        logger.info("USB scanner stopped")

    async def force_scan(self) -> None:
        """Force an immediate scan (useful for manual refresh)."""
        await self._scan_ports()

    async def reannounce_devices(self) -> None:
        """Re-emit discovery events for all known devices.

        Call this when a connection type gets enabled to re-announce
        devices that were previously discovered but ignored.
        """
        logger.debug(f"Re-announcing {len(self._known_devices)} USB devices")
        for device in self._known_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(device)
                except Exception as e:
                    logger.error(f"Error re-announcing USB device: {e}")

    async def _scan_loop(self) -> None:
        """Main scanning loop.

        On Windows, the USBHotplugMonitor triggers force_scan() when USB
        devices change, so we don't need to continuously poll.
        This is more efficient and matches the event-driven architecture.

        On Linux, we continue polling since it's lightweight.
        """
        # Windows: Don't continuously poll - wait for hotplug events
        if sys.platform == "win32":
            while self._running:
                try:
                    await asyncio.sleep(60)  # Heartbeat - no active scanning
                except asyncio.CancelledError:
                    break
            return

        # Linux/macOS: Continue polling (comports() is lightweight)
        while self._running:
            try:
                await asyncio.sleep(self._scan_interval)
                await self._scan_ports()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in USB scan loop: {e}")

    async def _scan_ports(self) -> None:
        """Scan for USB devices and detect changes."""
        try:
            # Run blocking comports() in thread
            ports = await asyncio.to_thread(serial.tools.list_ports.comports)
            current_ports: Set[str] = set()

            for port_info in ports:
                port = port_info.device
                current_ports.add(port)

                # Skip if already known
                if port in self._known_devices:
                    continue

                # Skip if no VID/PID
                if port_info.vid is None or port_info.pid is None:
                    continue

                # Try to identify device
                spec = identify_usb_device(port_info.vid, port_info.pid)
                if spec is None:
                    continue

                # New supported device found
                device = DiscoveredUSBDevice(
                    port=port,
                    device_type=spec.device_type,
                    spec=spec,
                    serial_number=port_info.serial_number,
                    description=port_info.description or spec.display_name,
                )

                self._known_devices[port] = device
                logger.info(f"USB device found: {spec.display_name} on {port}")

                if self._on_device_found:
                    try:
                        await self._on_device_found(device)
                    except Exception as e:
                        logger.error(f"Error in device found callback: {e}")

            # Check for disconnected devices
            lost_ports = set(self._known_devices.keys()) - current_ports
            for port in lost_ports:
                device = self._known_devices.pop(port)
                logger.info(f"USB device lost: {device.spec.display_name} on {port}")

                if self._on_device_lost:
                    try:
                        await self._on_device_lost(port)
                    except Exception as e:
                        logger.error(f"Error in device lost callback: {e}")

            self._known_ports = current_ports

        except Exception as e:
            logger.error(f"Error scanning USB ports: {e}")

    def get_device(self, port: str) -> Optional[DiscoveredUSBDevice]:
        """Get a specific device by port."""
        return self._known_devices.get(port)

    def get_devices_by_type(self, device_type: DeviceType) -> list[DiscoveredUSBDevice]:
        """Get all devices of a specific type."""
        return [d for d in self._known_devices.values() if d.device_type == device_type]

    def get_devices_by_module(self, module_id: str) -> list[DiscoveredUSBDevice]:
        """Get all devices that belong to a specific module."""
        return [
            d for d in self._known_devices.values()
            if d.spec.module_id == module_id
        ]
