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

from .base import CameraBackend, DiscoveredCamera, DiscoveredUSBCamera, AudioSiblingInfo


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
        return LinuxCameraBackend()

    elif platform.platform == "darwin":
        from .macos import MacOSCameraBackend
        return MacOSCameraBackend()

    else:
        # Windows and other platforms
        from .windows import WindowsCameraBackend
        return WindowsCameraBackend()


__all__ = [
    "get_camera_backend",
    "CameraBackend",
    "DiscoveredCamera",
    "DiscoveredUSBCamera",  # Backwards compatibility alias
    "AudioSiblingInfo",
]
