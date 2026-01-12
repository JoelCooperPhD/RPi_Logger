"""
Windows camera discovery backend.

Discovers cameras on Windows using OpenCV enumeration.
Currently uses generic names; could be enhanced with WMI for better device names.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

from rpi_logger.core.logging_utils import get_module_logger

from .base import DiscoveredUSBCamera

logger = get_module_logger("WindowsCameraBackend")

# Try to import OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("cv2 not available - camera discovery disabled")


class WindowsCameraBackend:
    """Windows camera discovery using OpenCV.

    This backend uses OpenCV enumeration for camera discovery.
    Currently provides generic names like "USB Camera 0".

    Future enhancement: Could use WMI (Windows Management Instrumentation)
    to get actual device names similar to how macOS uses AVFoundation.
    """

    def discover_cameras(self, max_devices: int = 4) -> list[DiscoveredUSBCamera]:
        """Discover cameras on Windows using OpenCV enumeration."""
        if not CV2_AVAILABLE:
            logger.debug("OpenCV not available, skipping camera discovery")
            return []

        cameras: list[DiscoveredUSBCamera] = []

        for index in range(max_devices):
            # Use DirectShow backend to avoid MSMF/Orbbec issues
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if cap and cap.isOpened():
                cap.release()
                cameras.append(DiscoveredUSBCamera(
                    device_id=f"usb:{index}",
                    stable_id=str(index),
                    dev_path=str(index),
                    friendly_name=f"USB Camera {index}",
                    hw_model="USB Camera",
                    location_hint=None,
                    camera_index=index,
                ))
                logger.debug(f"Discovered Windows camera at index {index}")
            else:
                if cap:
                    cap.release()
                break

        logger.debug(f"Discovered {len(cameras)} cameras on Windows")
        return cameras


__all__ = ["WindowsCameraBackend"]
