"""
USB Camera device scanner.

Discovers USB cameras using platform-specific backends:
- Linux: sysfs + OpenCV (real device names from kernel)
- macOS: AVFoundation + OpenCV (real device names via PyObjC)
- Windows: OpenCV enumeration (generic names, could add WMI)

This is separate from the CSI scanner which handles Pi cameras.
"""

import asyncio
from typing import Callable, Dict, Awaitable, Optional

from rpi_logger.core.logging_utils import get_module_logger

from .camera_backends import get_camera_backend, DiscoveredUSBCamera, CameraBackend

logger = get_module_logger("USBCameraScanner")

# Check OpenCV availability for backwards compatibility
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


# Callback types
USBCameraFoundCallback = Callable[[DiscoveredUSBCamera], Awaitable[None]]
USBCameraLostCallback = Callable[[str], Awaitable[None]]  # device_id


class USBCameraScanner:
    """
    Continuously scans for USB camera devices.

    Uses platform-specific backends for camera discovery:
    - Linux: LinuxCameraBackend (sysfs + OpenCV)
    - macOS: MacOSCameraBackend (AVFoundation + OpenCV)
    - Windows: WindowsCameraBackend (OpenCV)
    """

    DEFAULT_SCAN_INTERVAL = 2.0  # Scan every 2 seconds
    MAX_USB_DEVICES = 16

    def __init__(
        self,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
        on_device_found: Optional[USBCameraFoundCallback] = None,
        on_device_lost: Optional[USBCameraLostCallback] = None,
    ):
        self._scan_interval = scan_interval
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost

        self._known_devices: Dict[str, DiscoveredUSBCamera] = {}
        self._scan_task: Optional[asyncio.Task] = None
        self._running = False

        # Get platform-specific backend
        self._backend: CameraBackend = get_camera_backend()

    @property
    def devices(self) -> Dict[str, DiscoveredUSBCamera]:
        """Get currently known devices (device_id -> device)."""
        return dict(self._known_devices)

    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running

    async def start(self) -> None:
        """Start USB camera device scanning."""
        if self._running:
            return

        self._running = True

        # Perform initial scan immediately
        await self._scan_devices()

        # Start continuous scanning
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("USB camera scanner started")

    async def stop(self) -> None:
        """Stop USB camera device scanning."""
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
        logger.info("USB camera scanner stopped")

    async def force_scan(self) -> None:
        """Force an immediate scan."""
        if self._running:
            await self._scan_devices()

    async def reannounce_devices(self) -> None:
        """Re-emit discovery events for all known devices."""
        logger.debug(f"Re-announcing {len(self._known_devices)} USB cameras")
        for camera in self._known_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(camera)
                except Exception as e:
                    logger.error(f"Error re-announcing USB camera: {e}")

    async def _scan_loop(self) -> None:
        """Main scanning loop."""
        while self._running:
            try:
                await asyncio.sleep(self._scan_interval)
                await self._scan_devices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in USB camera scan loop: {e}")

    async def _scan_devices(self) -> None:
        """Scan for USB cameras and detect changes."""
        current_devices: Dict[str, DiscoveredUSBCamera] = {}

        # Discover USB cameras (runs in thread to avoid blocking)
        cameras = await asyncio.to_thread(self._discover_usb_sync)
        for cam in cameras:
            current_devices[cam.device_id] = cam

        # Detect new devices
        for device_id, camera in current_devices.items():
            if device_id not in self._known_devices:
                self._known_devices[device_id] = camera
                logger.info(f"USB camera found: {camera.friendly_name} ({device_id})")
                if self._on_device_found:
                    try:
                        await self._on_device_found(camera)
                    except Exception as e:
                        logger.error(f"Error in device found callback: {e}")

        # Detect lost devices
        lost = set(self._known_devices.keys()) - set(current_devices.keys())
        for device_id in lost:
            camera = self._known_devices.pop(device_id)
            logger.info(f"USB camera lost: {camera.friendly_name} ({device_id})")
            if self._on_device_lost:
                try:
                    await self._on_device_lost(device_id)
                except Exception as e:
                    logger.error(f"Error in device lost callback: {e}")

    def _discover_usb_sync(self) -> list[DiscoveredUSBCamera]:
        """Synchronous USB camera discovery (runs in thread).

        Delegates to the platform-specific backend for actual discovery.
        """
        return self._backend.discover_cameras(self.MAX_USB_DEVICES)

    def get_device(self, device_id: str) -> Optional[DiscoveredUSBCamera]:
        """Get a specific device by ID."""
        return self._known_devices.get(device_id)


__all__ = [
    "USBCameraScanner",
    "DiscoveredUSBCamera",
    "USBCameraFoundCallback",
    "USBCameraLostCallback",
    "CV2_AVAILABLE",
]
