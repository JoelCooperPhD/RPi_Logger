"""
Base protocol for camera discovery backends.

Each platform (Linux, macOS, Windows) has its own backend implementation
that provides camera discovery using platform-specific APIs.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class DiscoveredUSBCamera:
    """Represents a discovered USB camera device.

    This is the common data structure returned by all camera backends.
    It contains all information needed to identify and use a camera.

    Attributes:
        device_id: Unique identifier for this camera (e.g., "usb:0", "usb:usb1-2")
        stable_id: Persistent identifier that survives reboots (USB path or unique ID)
        dev_path: Platform-specific device path (e.g., "/dev/video0" on Linux, index on macOS)
        friendly_name: Human-readable name for display (e.g., "FaceTime HD Camera")
        hw_model: Hardware model identifier if known
        location_hint: Physical location hint (USB port path on Linux)
    """

    device_id: str
    stable_id: str
    dev_path: Optional[str]
    friendly_name: str
    hw_model: Optional[str]
    location_hint: Optional[str]


class CameraBackend(Protocol):
    """Protocol for platform-specific camera discovery backends.

    Each platform implements this protocol to provide camera discovery
    using the most appropriate APIs for that platform:
    - Linux: sysfs + OpenCV
    - macOS: AVFoundation + OpenCV
    - Windows: OpenCV (+ WMI for future enhancement)
    """

    def discover_cameras(self, max_devices: int = 16) -> list[DiscoveredUSBCamera]:
        """Discover available cameras on this platform.

        Args:
            max_devices: Maximum number of devices to enumerate.

        Returns:
            List of discovered cameras with full device information.
        """
        ...


__all__ = [
    "DiscoveredUSBCamera",
    "CameraBackend",
]
