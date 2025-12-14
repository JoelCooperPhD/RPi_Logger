"""
macOS camera discovery backend.

Discovers cameras on macOS using AVFoundation for device enumeration and
OpenCV for capture verification. AVFoundation provides actual device names
like "FaceTime HD Camera" instead of generic "USB Camera 0".

Requires PyObjC (pyobjc-framework-AVFoundation) for AVFoundation access.
Falls back to generic names if PyObjC is not available.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger

from .base import DiscoveredUSBCamera

logger = get_module_logger("MacOSCameraBackend")

# Try to import OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("cv2 not available - camera discovery disabled")


class MacOSCameraBackend:
    """macOS camera discovery using AVFoundation and OpenCV.

    This backend uses AVFoundation (via PyObjC) to get actual device names
    and unique identifiers, then verifies camera accessibility with OpenCV.

    AVFoundation provides:
    - localizedName(): Human-readable name (e.g., "FaceTime HD Camera")
    - uniqueID(): Persistent identifier that survives reboots
    - modelID(): Hardware model identifier

    The enumeration order from AVFoundation matches OpenCV's camera indices,
    allowing us to correlate the rich device info with OpenCV capture.
    """

    def discover_cameras(self, max_devices: int = 16) -> list[DiscoveredUSBCamera]:
        """Discover cameras on macOS using AVFoundation + OpenCV."""
        if not CV2_AVAILABLE:
            logger.debug("OpenCV not available, skipping camera discovery")
            return []

        cameras: list[DiscoveredUSBCamera] = []

        # Try to get device info from AVFoundation for better names
        av_devices = self._get_avfoundation_devices()

        for index in range(max_devices):
            cap = cv2.VideoCapture(index)
            if cap and cap.isOpened():
                cap.release()

                # Use AVFoundation info if available, otherwise generic names
                if av_devices and index < len(av_devices):
                    name, unique_id, model_id = av_devices[index]
                    friendly_name = name
                    hw_model = model_id or name
                    stable_id = unique_id or str(index)
                else:
                    friendly_name = f"USB Camera {index}"
                    hw_model = "USB Camera"
                    stable_id = str(index)

                cameras.append(DiscoveredUSBCamera(
                    device_id=f"usb:{index}",
                    stable_id=stable_id,
                    dev_path=str(index),
                    friendly_name=friendly_name,
                    hw_model=hw_model,
                    location_hint=None,
                ))
                logger.debug(f"Discovered macOS camera at index {index}: {friendly_name}")
            else:
                if cap:
                    cap.release()
                break

        logger.debug(f"Discovered {len(cameras)} cameras on macOS")
        return cameras

    def _get_avfoundation_devices(self) -> Optional[list[tuple[str, str, str]]]:
        """Get camera info from AVFoundation (macOS only).

        AVFoundation provides actual device names, unique IDs, and model info
        that OpenCV cannot access directly.

        Returns:
            List of (name, unique_id, model_id) tuples in enumeration order,
            or None if AVFoundation/PyObjC is not available.
        """
        try:
            from AVFoundation import AVCaptureDevice, AVMediaTypeVideo

            devices = AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo)
            result = []
            for device in devices:
                name = device.localizedName() or "Unknown Camera"
                unique_id = device.uniqueID() or ""
                model_id = device.modelID() or ""
                result.append((name, unique_id, model_id))
                logger.debug(f"AVFoundation device: {name} (model: {model_id})")

            return result if result else None

        except ImportError:
            logger.debug("PyObjC AVFoundation not available, using generic camera names")
            return None
        except Exception as e:
            logger.warning(f"Failed to enumerate AVFoundation devices: {e}")
            return None


__all__ = ["MacOSCameraBackend"]
