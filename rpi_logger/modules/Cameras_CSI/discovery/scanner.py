"""
CSI (Camera Serial Interface) scanner for Raspberry Pi cameras.

Discovers Pi CSI cameras using libcamera-hello CLI tool.
This avoids importing Picamera2 in the parent process, which would
prevent child processes from accessing cameras.
"""

import asyncio
import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Awaitable

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("CSIScanner")


# Check which camera CLI tool is available (rpicam-hello or libcamera-hello)
def _find_camera_cli() -> Optional[str]:
    for cmd in ["rpicam-hello", "libcamera-hello"]:
        try:
            result = subprocess.run(
                [cmd, "--version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return cmd
        except Exception:
            continue
    return None


CAMERA_CLI = _find_camera_cli()
LIBCAMERA_AVAILABLE = CAMERA_CLI is not None

# For backwards compatibility
PICAMERA2_AVAILABLE = LIBCAMERA_AVAILABLE


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
    Scans for CSI camera devices (Raspberry Pi cameras).

    Uses libcamera-hello --list-cameras to discover cameras without
    importing Picamera2, which would prevent child processes from
    accessing cameras.
    """

    DEFAULT_SCAN_INTERVAL = 2.0

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
        """Start CSI camera device scanning.

        CSI cameras are hardwired (not hot-pluggable), so we only scan once
        on startup. Uses libcamera-hello CLI to avoid polluting libcamera
        state in the parent process.
        """
        if self._running:
            return

        if not LIBCAMERA_AVAILABLE:
            logger.debug("Cannot start CSI scanner - libcamera-hello not available")
            return

        self._running = True

        # Single scan - CSI cameras are hardwired
        await self._scan_devices()

        logger.info(f"CSI camera scanner started - found {len(self._known_devices)} cameras")

    async def stop(self) -> None:
        """Stop CSI camera device scanning."""
        if not self._running:
            return

        self._running = False

        for device_id in list(self._known_devices.keys()):
            if self._on_device_lost:
                try:
                    await self._on_device_lost(device_id)
                except Exception as e:
                    logger.warning(f"Error in device lost callback: {e}")

        self._known_devices.clear()
        logger.info("CSI camera scanner stopped")

    async def force_scan(self) -> None:
        """Force an immediate scan."""
        if self._running:
            await self._scan_devices()

    async def reannounce_devices(self) -> None:
        """Re-emit discovery events for all known devices."""
        for camera in self._known_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(camera)
                except Exception as e:
                    logger.warning(f"Error re-announcing CSI camera: {e}")

    async def _scan_devices(self) -> None:
        """Scan for CSI cameras and detect changes."""
        current_devices: Dict[str, DiscoveredCSICamera] = {}

        # Discover cameras via CLI (runs in thread to avoid blocking)
        cameras = await asyncio.to_thread(self._discover_via_cli)
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
                        logger.warning(f"Error in device found callback: {e}")

        # Detect lost devices
        lost = set(self._known_devices.keys()) - set(current_devices.keys())
        for device_id in lost:
            camera = self._known_devices.pop(device_id)
            logger.info(f"CSI camera lost: {camera.friendly_name} ({device_id})")
            if self._on_device_lost:
                try:
                    await self._on_device_lost(device_id)
                except Exception as e:
                    logger.warning(f"Error in device lost callback: {e}")

    def _discover_via_cli(self) -> list[DiscoveredCSICamera]:
        """Discover CSI cameras using libcamera-hello CLI."""
        cameras: list[DiscoveredCSICamera] = []

        if not CAMERA_CLI:
            return cameras

        try:
            result = subprocess.run(
                [CAMERA_CLI, "--list-cameras"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return cameras

            # Parse output like:
            # Available cameras
            # -----------------
            # 0 : imx296 [1456x1088 10-bit MONO] (/base/axi/pcie@...)
            #     Modes: 'SBGGR10_CSI2P' : 1456x1088 [60.39 fps - (0, 0)/1456x1088 crop]

            output = result.stdout + result.stderr  # Sometimes output goes to stderr

            # Pattern: "N : model [resolution] (location)"
            pattern = r'^(\d+)\s*:\s*(\w+)\s*\[([^\]]+)\]\s*\(([^)]+)\)'

            for line in output.split('\n'):
                line = line.strip()
                match = re.match(pattern, line)
                if match:
                    cam_num = match.group(1)
                    model = match.group(2)
                    location = match.group(4)

                    # Skip USB cameras that might show up
                    if 'usb' in location.lower():
                        continue

                    cameras.append(DiscoveredCSICamera(
                        device_id=f"picam:{cam_num}",
                        stable_id=cam_num,
                        friendly_name=f"RPi:Cam{cam_num}",
                        hw_model=model,
                        location_hint=location,
                    ))

        except subprocess.TimeoutExpired:
            logger.warning("libcamera-hello timed out")
        except Exception as exc:
            logger.warning(f"CSI camera discovery failed: {exc}")

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
    "LIBCAMERA_AVAILABLE",
]
