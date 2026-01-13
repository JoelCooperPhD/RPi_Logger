"""
EyeTracker module discovery package.

Provides Pupil Labs eye tracker discovery using mDNS/Zeroconf.
"""

from rpi_logger.core.devices.discovery_protocol import (
    BaseModuleDiscovery,
    DeviceFoundCallback,
    DeviceLostCallback,
)
from .spec import DISCOVERY_SPEC
from .scanner import (
    NetworkScanner,
    DiscoveredNetworkDevice,
    ZEROCONF_AVAILABLE,
)


class EyeTrackerDiscovery(BaseModuleDiscovery):
    """Discovery handler for Pupil Labs eye trackers."""

    spec = DISCOVERY_SPEC

    def create_scanner(
        self,
        on_found: DeviceFoundCallback,
        on_lost: DeviceLostCallback,
    ) -> NetworkScanner:
        """Create network scanner with callbacks."""
        return NetworkScanner(
            on_device_found=on_found,
            on_device_lost=on_lost,
        )


# Exports for discovery loader
__all__ = [
    "EyeTrackerDiscovery",
    "DISCOVERY_SPEC",
    "NetworkScanner",
    "DiscoveredNetworkDevice",
    "ZEROCONF_AVAILABLE",
]
