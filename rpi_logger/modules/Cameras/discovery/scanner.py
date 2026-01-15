"""
Camera device scanner.

Discovers cameras using platform-specific backends:
- Linux: sysfs + OpenCV (real device names from kernel)
- macOS: AVFoundation + OpenCV (real device names via PyObjC)
- Windows: OpenCV enumeration (generic names, could add WMI)

This is separate from the CSI scanner which handles Pi cameras.
"""

import asyncio
import os
import sys
from typing import Callable, Dict, Awaitable, Optional

# Disable MSMF hardware transforms on Windows to fix slow camera initialization.
# Must be set BEFORE importing cv2. See: https://github.com/opencv/opencv/issues/17687
if sys.platform == "win32":
    os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

from rpi_logger.core.logging_utils import get_module_logger

from .backends import get_camera_backend, DiscoveredCamera, DiscoveredUSBCamera, CameraBackend

logger = get_module_logger("CameraScanner")

# Check OpenCV availability for backwards compatibility
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


# Callback types
CameraFoundCallback = Callable[[DiscoveredCamera], Awaitable[None]]
CameraLostCallback = Callable[[str], Awaitable[None]]  # device_id

# Backwards compatibility aliases
USBCameraFoundCallback = CameraFoundCallback
USBCameraLostCallback = CameraLostCallback


class CameraScanner:
    """
    Continuously scans for camera devices.

    Uses platform-specific backends for camera discovery:
    - Linux: LinuxCameraBackend (sysfs + OpenCV)
    - macOS: MacOSCameraBackend (AVFoundation + OpenCV)
    - Windows: WindowsCameraBackend (OpenCV)
    """

    # Windows: OpenCV VideoCapture activates camera hardware, causing lights to flash.
    # Use longer interval on Windows to reduce flashing and Orbbec sensor noise.
    DEFAULT_SCAN_INTERVAL = 30.0 if sys.platform == "win32" else 2.0
    MAX_DEVICES = 16

    def __init__(
        self,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
        on_device_found: Optional[CameraFoundCallback] = None,
        on_device_lost: Optional[CameraLostCallback] = None,
    ):
        self._scan_interval = scan_interval
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost

        self._known_devices: Dict[str, DiscoveredCamera] = {}
        self._scan_task: Optional[asyncio.Task] = None
        self._running = False

        # Get platform-specific backend
        self._backend: CameraBackend = get_camera_backend()

    @property
    def devices(self) -> Dict[str, DiscoveredCamera]:
        """Get currently known devices (device_id -> device)."""
        return dict(self._known_devices)

    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running

    async def start(self) -> None:
        """Start camera device scanning."""
        if self._running:
            return

        self._running = True

        # Perform initial scan immediately
        await self._scan_devices()

        # Start continuous scanning
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("Camera scanner started")

    async def stop(self) -> None:
        """Stop camera device scanning."""
        if not self._running:
            return

        self._running = False

        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None

        # Notify about lost devices
        for device_id in list(self._known_devices.keys()):
            if self._on_device_lost:
                try:
                    await self._on_device_lost(device_id)
                except Exception as e:
                    logger.error(f"Error in device lost callback: {e}")

        self._known_devices.clear()
        logger.info("Camera scanner stopped")

    async def force_scan(self) -> None:
        """Force an immediate scan."""
        if self._running:
            await self._scan_devices()

    async def reannounce_devices(self) -> None:
        """Re-emit discovery events for all known devices."""
        logger.debug(f"Re-announcing {len(self._known_devices)} cameras")
        for camera in self._known_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(camera)
                except Exception as e:
                    logger.error(f"Error re-announcing camera: {e}")

    async def _scan_loop(self) -> None:
        """Main scanning loop.

        On Windows and macOS, we don't continuously poll - the USBHotplugMonitor
        calls force_scan() when USB devices change. On Windows this prevents
        camera lights from flashing; on macOS it provides consistent behavior.

        On Linux, we continue polling since sysfs is lightweight.
        """
        # Windows/macOS: Don't continuously poll - wait for hotplug events
        if sys.platform in ("win32", "darwin"):
            # Just keep the task alive, actual scanning triggered by hotplug
            while self._running:
                try:
                    await asyncio.sleep(60)  # Heartbeat - no active scanning
                except asyncio.CancelledError:
                    break
            return

        # Linux: Continue polling (sysfs is lightweight)
        while self._running:
            try:
                await asyncio.sleep(self._scan_interval)
                await self._scan_devices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in camera scan loop: {e}")

    async def _scan_devices(self) -> None:
        """Scan for cameras and detect changes."""
        current_devices: Dict[str, DiscoveredCamera] = {}

        # Discover cameras (runs in thread to avoid blocking)
        cameras = await asyncio.to_thread(self._discover_cameras_sync)
        for cam in cameras:
            current_devices[cam.device_id] = cam

        # Detect new devices
        for device_id, camera in current_devices.items():
            if device_id not in self._known_devices:
                self._known_devices[device_id] = camera
                logger.info(f"Camera found: {camera.friendly_name} ({device_id})")
                if self._on_device_found:
                    try:
                        await self._on_device_found(camera)
                    except Exception as e:
                        logger.error(f"Error in device found callback: {e}")

        # Detect lost devices
        lost = set(self._known_devices.keys()) - set(current_devices.keys())
        for device_id in lost:
            # On Windows, cameras in use can't be opened by VideoCapture.
            # Don't remove them - they're likely in use, not unplugged.
            if sys.platform == "win32":
                logger.debug(f"Camera {device_id} not visible - likely in use by module")
                continue

            camera = self._known_devices.pop(device_id)
            logger.info(f"Camera lost: {camera.friendly_name} ({device_id})")
            if self._on_device_lost:
                try:
                    await self._on_device_lost(device_id)
                except Exception as e:
                    logger.error(f"Error in device lost callback: {e}")

    def _discover_cameras_sync(self) -> list[DiscoveredCamera]:
        """Synchronous camera discovery (runs in thread).

        Delegates to the platform-specific backend for actual discovery.
        """
        return self._backend.discover_cameras(self.MAX_DEVICES)

    def get_device(self, device_id: str) -> Optional[DiscoveredCamera]:
        """Get a specific device by ID."""
        return self._known_devices.get(device_id)


# Backwards compatibility alias
USBCameraScanner = CameraScanner

__all__ = [
    "CameraScanner",
    "USBCameraScanner",  # Backwards compatibility alias
    "DiscoveredCamera",
    "DiscoveredUSBCamera",  # Backwards compatibility alias
    "CameraFoundCallback",
    "CameraLostCallback",
    "USBCameraFoundCallback",  # Backwards compatibility alias
    "USBCameraLostCallback",  # Backwards compatibility alias
    "CV2_AVAILABLE",
]
