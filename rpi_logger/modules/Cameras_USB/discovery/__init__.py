"""
Cameras_USB module discovery package.

Provides USB camera discovery using platform-specific backends:
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
from .scanner import CameraScanner, DiscoveredUSBCamera, CV2_AVAILABLE
from .backends import get_camera_backend, CameraBackend, AudioSiblingInfo


class CamerasUSBDiscovery(BaseModuleDiscovery):
    """Discovery handler for USB cameras."""

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


# Exports for discovery loader
__all__ = [
    "CamerasUSBDiscovery",
    "DISCOVERY_SPEC",
    "CameraScanner",
    "DiscoveredUSBCamera",
    "AudioSiblingInfo",
    "get_camera_backend",
    "CameraBackend",
    "CV2_AVAILABLE",
]
