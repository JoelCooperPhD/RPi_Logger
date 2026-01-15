"""
Cameras module discovery package.

Provides camera discovery using platform-specific backends:
- Linux: sysfs + OpenCV (with audio sibling detection via ALSA)
- macOS: AVFoundation + OpenCV
- Windows: OpenCV + WMI (with audio sibling detection via VID:PID)
"""

from typing import Callable, Awaitable

from rpi_logger.core.devices.discovery_protocol import (
    BaseModuleDiscovery,
    DeviceFoundCallback,
    DeviceLostCallback,
)
from .spec import DISCOVERY_SPEC
from .scanner import CameraScanner, DiscoveredCamera, DiscoveredUSBCamera, CV2_AVAILABLE
from .backends import get_camera_backend, CameraBackend, AudioSiblingInfo


class CamerasDiscovery(BaseModuleDiscovery):
    """Discovery handler for cameras."""

    spec = DISCOVERY_SPEC

    def create_scanner(
        self,
        on_found: DeviceFoundCallback,
        on_lost: DeviceLostCallback,
    ) -> CameraScanner:
        """Create camera scanner with callbacks."""
        return CameraScanner(
            on_device_found=on_found,
            on_device_lost=on_lost,
        )


# Backwards compatibility alias
CamerasUSBDiscovery = CamerasDiscovery

# Exports for discovery loader
__all__ = [
    "CamerasDiscovery",
    "CamerasUSBDiscovery",  # Backwards compatibility alias
    "DISCOVERY_SPEC",
    "CameraScanner",
    "DiscoveredCamera",
    "DiscoveredUSBCamera",  # Backwards compatibility alias
    "AudioSiblingInfo",
    "get_camera_backend",
    "CameraBackend",
    "CV2_AVAILABLE",
]
