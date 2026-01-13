"""
Cameras_CSI module discovery package.

Provides Pi CSI camera discovery using libcamera CLI.
"""

from rpi_logger.core.devices.discovery_protocol import (
    BaseModuleDiscovery,
    DeviceFoundCallback,
    DeviceLostCallback,
)
from .spec import DISCOVERY_SPEC
from .scanner import (
    CSIScanner,
    DiscoveredCSICamera,
    LIBCAMERA_AVAILABLE,
    PICAMERA2_AVAILABLE,
)


class CamerasCSIDiscovery(BaseModuleDiscovery):
    """Discovery handler for Pi CSI cameras."""

    spec = DISCOVERY_SPEC

    def create_scanner(
        self,
        on_found: DeviceFoundCallback,
        on_lost: DeviceLostCallback,
    ) -> CSIScanner:
        """Create CSI scanner with callbacks."""
        return CSIScanner(
            on_device_found=on_found,
            on_device_lost=on_lost,
        )


# Exports for discovery loader
__all__ = [
    "CamerasCSIDiscovery",
    "DISCOVERY_SPEC",
    "CSIScanner",
    "DiscoveredCSICamera",
    "LIBCAMERA_AVAILABLE",
    "PICAMERA2_AVAILABLE",
]
