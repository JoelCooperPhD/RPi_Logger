"""
CSI (Camera Serial Interface) scanner for Raspberry Pi cameras.

Discovers Pi CSI cameras using Picamera2.
This is separate from the USB camera scanner.
"""

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Awaitable

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("CSIScanner")

# Try to import Picamera2 - required for Pi camera discovery
try:
    from picamera2 import Picamera2  # type: ignore
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False
    logger.debug("Picamera2 not available - Pi camera discovery disabled")


@dataclass
class DiscoveredCSICamera:
    """Represents a discovered CSI (Pi) camera device."""
    device_id: str           # Unique ID (e.g., "picam:0")
    stable_id: str           # Camera number
    friendly_name: str       # Display name
    hw_model: Optional[str]  # Hardware model if known
    location_hint: Optional[str]  # CSI connector info


# Callback types
CSICameraFoundCallback = Callable[[DiscoveredCSICamera], Awaitable[None]]
CSICameraLostCallback = Callable[[str], Awaitable[None]]  # device_id


class CSIScanner:
    """
    Continuously scans for CSI camera devices (Raspberry Pi cameras).

    Discovers Pi cameras via Picamera2.global_camera_info().
    """

    DEFAULT_SCAN_INTERVAL = 2.0  # Scan every 2 seconds

    def __init__(
        self,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
        on_device_found: Optional[CSICameraFoundCallback] = None,
        on_device_lost: Optional[CSICameraLostCallback] = None,
    ):
        self._scan_interval = scan_interval
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost

        self._known_devices: Dict[str, DiscoveredCSICamera] = {}
        self._scan_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def devices(self) -> Dict[str, DiscoveredCSICamera]:
        """Get currently known devices (device_id -> device)."""
        return dict(self._known_devices)

    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running

    async def start(self) -> None:
        """Start CSI camera device scanning."""
        if self._running:
            return

        if not PICAMERA2_AVAILABLE:
            logger.debug("Cannot start CSI scanner - Picamera2 not available")
            return

        self._running = True

        # Perform initial scan immediately
        await self._scan_devices()

        # Start continuous scanning
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("CSI camera scanner started")

    async def stop(self) -> None:
        """Stop CSI camera device scanning."""
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
        logger.info("CSI camera scanner stopped")

    async def force_scan(self) -> None:
        """Force an immediate scan."""
        if self._running:
            await self._scan_devices()

    async def reannounce_devices(self) -> None:
        """Re-emit discovery events for all known devices."""
        logger.debug(f"Re-announcing {len(self._known_devices)} CSI cameras")
        for camera in self._known_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(camera)
                except Exception as e:
                    logger.error(f"Error re-announcing CSI camera: {e}")

    async def _scan_loop(self) -> None:
        """Main scanning loop."""
        while self._running:
            try:
                await asyncio.sleep(self._scan_interval)
                await self._scan_devices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in CSI camera scan loop: {e}")

    async def _scan_devices(self) -> None:
        """Scan for CSI cameras and detect changes."""
        current_devices: Dict[str, DiscoveredCSICamera] = {}

        # Discover Pi cameras (runs in thread to avoid blocking)
        cameras = await asyncio.to_thread(self._discover_picam_sync)
        for cam in cameras:
            current_devices[cam.device_id] = cam

        # Detect new devices
        for device_id, camera in current_devices.items():
            if device_id not in self._known_devices:
                self._known_devices[device_id] = camera
                logger.info(f"CSI camera found: {camera.friendly_name} ({device_id})")
                if self._on_device_found:
                    try:
                        await self._on_device_found(camera)
                    except Exception as e:
                        logger.error(f"Error in device found callback: {e}")

        # Detect lost devices
        lost = set(self._known_devices.keys()) - set(current_devices.keys())
        for device_id in lost:
            camera = self._known_devices.pop(device_id)
            logger.info(f"CSI camera lost: {camera.friendly_name} ({device_id})")
            if self._on_device_lost:
                try:
                    await self._on_device_lost(device_id)
                except Exception as e:
                    logger.error(f"Error in device lost callback: {e}")

    def _discover_picam_sync(self) -> list[DiscoveredCSICamera]:
        """Synchronous Pi camera discovery (runs in thread)."""
        cameras: list[DiscoveredCSICamera] = []

        if not PICAMERA2_AVAILABLE:
            return cameras

        try:
            cam_info_list = Picamera2.global_camera_info()
        except Exception as exc:
            logger.warning(f"Picamera2 discovery failed: {exc}")
            return cameras

        for idx, info in enumerate(cam_info_list):
            model = info.get("Model") or ""
            cam_id = info.get("Id") or ""

            # Skip non-CSI cameras that show up via libcamera (e.g., UVC).
            if "usb@" in cam_id or model.lower().startswith("uvc"):
                logger.debug(f"Skipping non-CSI camera entry: {cam_id or model}")
                continue

            sensor_id = info.get("SensorId")
            stable_id = str(info.get("Num")) if info.get("Num") is not None else str(sensor_id or cam_id or idx)
            friendly_label = f"RPi:Cam{stable_id}" if str(stable_id).isdigit() else f"RPi:Cam{idx}"

            cameras.append(DiscoveredCSICamera(
                device_id=f"picam:{stable_id}",
                stable_id=stable_id,
                friendly_name=friendly_label,
                hw_model=model or None,
                location_hint=cam_id or None,
            ))

        logger.debug(f"Discovered {len(cameras)} CSI cameras")
        return cameras

    def get_device(self, device_id: str) -> Optional[DiscoveredCSICamera]:
        """Get a specific device by ID."""
        return self._known_devices.get(device_id)


__all__ = [
    "CSIScanner",
    "DiscoveredCSICamera",
    "CSICameraFoundCallback",
    "CSICameraLostCallback",
    "PICAMERA2_AVAILABLE",
]
