"""
Scanner for internal/virtual devices.

Internal devices are software-only modules that don't require hardware scanning.
They are always available and are "discovered" immediately on startup.

Examples: Notes module
"""

from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List

from rpi_logger.core.logging_utils import get_module_logger
from .types import DeviceType
from .device_registry import DEVICE_REGISTRY, DeviceSpec

logger = get_module_logger("InternalDeviceScanner")


@dataclass
class DiscoveredInternalDevice:
    """Information about a discovered internal device."""
    device_id: str
    device_type: DeviceType
    spec: DeviceSpec


# Callback types
InternalDeviceFoundCallback = Callable[[DiscoveredInternalDevice], Awaitable[None]]
InternalDeviceLostCallback = Callable[[str], Awaitable[None]]


def get_internal_device_specs() -> List[DeviceSpec]:
    """Get all device specs marked as internal."""
    return [
        spec for spec in DEVICE_REGISTRY.values()
        if getattr(spec, 'is_internal', False)
    ]


class InternalDeviceScanner:
    """
    Scanner for internal/virtual devices.

    Unlike USB/XBee/Network scanners that poll for hardware,
    this scanner immediately "discovers" all internal devices
    defined in the device registry when started.
    """

    def __init__(
        self,
        on_device_found: InternalDeviceFoundCallback,
        on_device_lost: InternalDeviceLostCallback,
    ):
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost
        self._active_devices: Dict[str, DiscoveredInternalDevice] = {}
        self._running = False

    async def start(self) -> None:
        """Start the scanner and discover all internal devices immediately."""
        if self._running:
            return

        self._running = True
        logger.info("Internal device scanner started")

        # Discover all internal devices from registry
        for spec in get_internal_device_specs():
            device_id = f"internal_{spec.module_id.lower()}"
            device = DiscoveredInternalDevice(
                device_id=device_id,
                device_type=spec.device_type,
                spec=spec,
            )
            self._active_devices[device_id] = device
            logger.debug(f"Internal device discovered: {spec.display_name} ({device_id})")
            await self._on_device_found(device)

    async def stop(self) -> None:
        """Stop the scanner and remove all internal devices."""
        if not self._running:
            return

        self._running = False

        # Notify about device loss
        for device_id in list(self._active_devices.keys()):
            await self._on_device_lost(device_id)

        self._active_devices.clear()
        logger.info("Internal device scanner stopped")

    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running

    async def reannounce_devices(self) -> None:
        """Re-emit discovery events for all known devices."""
        for device in self._active_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(device)
                except Exception as e:
                    logger.error(f"Error re-announcing internal device: {e}")

    def get_devices(self) -> List[DiscoveredInternalDevice]:
        """Get all currently discovered internal devices."""
        return list(self._active_devices.values())
