"""
Scanner for UART devices with fixed paths.

UART devices (like GPS on Raspberry Pi) are connected to fixed hardware paths
that don't change dynamically. This scanner checks for the existence of these
paths on startup and emits device found/lost events.

Unlike USB scanning, UART devices are not hot-pluggable - they're either
present (path exists) or not (path doesn't exist), checked once on startup.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Dict, List

from rpi_logger.core.logging_utils import get_module_logger
from .types import DeviceType
from .device_registry import DeviceSpec, get_uart_device_specs

logger = get_module_logger("UARTScanner")


@dataclass
class DiscoveredUARTDevice:
    """Information about a discovered UART device."""
    device_id: str          # Unique ID based on path
    device_type: DeviceType
    spec: DeviceSpec
    path: str               # The actual device path (e.g., /dev/serial0)


# Callback types
UARTDeviceFoundCallback = Callable[[DiscoveredUARTDevice], Awaitable[None]]
UARTDeviceLostCallback = Callable[[str], Awaitable[None]]


class UARTScanner:
    """
    Scanner for UART devices with fixed paths.

    Unlike USB/XBee scanners that poll continuously, this scanner only
    checks for device presence on startup. UART devices on the Pi are
    fixed hardware - they don't appear/disappear dynamically.
    """

    def __init__(
        self,
        on_device_found: UARTDeviceFoundCallback,
        on_device_lost: UARTDeviceLostCallback,
    ):
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost
        self._active_devices: Dict[str, DiscoveredUARTDevice] = {}
        self._running = False

    async def start(self) -> None:
        """Start the scanner and discover all UART devices with existing paths."""
        if self._running:
            return

        self._running = True
        logger.info("UART device scanner started")

        # Check all UART devices from registry
        for spec in get_uart_device_specs():
            if not spec.fixed_path:
                continue

            path = Path(spec.fixed_path)
            if path.exists():
                device_id = f"uart_{spec.module_id.lower()}"
                device = DiscoveredUARTDevice(
                    device_id=device_id,
                    device_type=spec.device_type,
                    spec=spec,
                    path=spec.fixed_path,
                )
                self._active_devices[device_id] = device
                logger.info(
                    "UART device discovered: %s at %s (%s)",
                    spec.display_name, spec.fixed_path, device_id
                )
                await self._on_device_found(device)
            else:
                logger.debug(
                    "UART device path not found: %s for %s",
                    spec.fixed_path, spec.display_name
                )

    async def stop(self) -> None:
        """Stop the scanner and remove all UART devices."""
        if not self._running:
            return

        self._running = False

        # Notify about device loss
        for device_id in list(self._active_devices.keys()):
            await self._on_device_lost(device_id)

        self._active_devices.clear()
        logger.info("UART device scanner stopped")

    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running

    async def reannounce_devices(self) -> None:
        """Re-emit discovery events for all known devices."""
        logger.debug(f"Re-announcing {len(self._active_devices)} UART devices")
        for device in self._active_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(device)
                except Exception as e:
                    logger.error(f"Error re-announcing UART device: {e}")

    def get_devices(self) -> List[DiscoveredUARTDevice]:
        """Get all currently discovered UART devices."""
        return list(self._active_devices.values())

    def get_device(self, device_id: str) -> DiscoveredUARTDevice | None:
        """Get a specific device by ID."""
        return self._active_devices.get(device_id)
