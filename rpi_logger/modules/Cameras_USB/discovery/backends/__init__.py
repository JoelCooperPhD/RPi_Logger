"""
Camera discovery backends.

Platform-specific camera discovery implementations using the most appropriate
APIs for each platform:
- Linux: sysfs + OpenCV
- macOS: AVFoundation + OpenCV
- Windows: OpenCV (+ WMI for future enhancement)

The get_camera_backend() factory uses PlatformInfo to select the appropriate
backend for the current platform.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

from rpi_logger.core.platform_info import get_platform_info
from rpi_logger.core.logging_utils import get_module_logger

from .base import CameraBackend, DiscoveredUSBCamera, AudioSiblingInfo

logger = get_module_logger("CameraBackends")


def get_camera_backend() -> CameraBackend:
    """Factory to get the appropriate camera backend for the current platform.

    Uses PlatformInfo to determine which backend to instantiate.
    Backends are imported lazily to avoid loading unnecessary dependencies.

    Returns:
        CameraBackend instance for the current platform.
    """
    platform = get_platform_info()

    if platform.platform == "linux":
        from .linux import LinuxCameraBackend
        logger.debug("Using Linux camera backend (sysfs + OpenCV)")
        return LinuxCameraBackend()

    elif platform.platform == "darwin":
        from .macos import MacOSCameraBackend
        logger.debug("Using macOS camera backend (AVFoundation + OpenCV)")
        return MacOSCameraBackend()

    else:
        # Windows and other platforms
        from .windows import WindowsCameraBackend
        logger.debug("Using Windows camera backend (OpenCV)")
        return WindowsCameraBackend()


__all__ = [
    "get_camera_backend",
    "CameraBackend",
    "DiscoveredUSBCamera",
    "AudioSiblingInfo",
]
