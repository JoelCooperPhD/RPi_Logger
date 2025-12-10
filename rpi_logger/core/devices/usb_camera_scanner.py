"""
USB Camera device scanner.

Discovers USB cameras using:
- Linux: /dev/video* + sysfs enumeration
- macOS/Windows: OpenCV enumeration

This is separate from the CSI scanner which handles Pi cameras.
"""

import asyncio
import glob
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Dict, Awaitable

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("USBCameraScanner")

# Try to import OpenCV - required for USB camera discovery
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("cv2 not available - USB camera discovery disabled")


@dataclass
class DiscoveredUSBCamera:
    """Represents a discovered USB camera device."""
    device_id: str           # Unique ID (e.g., "usb:usb1-2")
    stable_id: str           # USB bus path
    dev_path: Optional[str]  # /dev/video* path
    friendly_name: str       # Display name
    hw_model: Optional[str]  # Hardware model if known
    location_hint: Optional[str]  # USB port path


# Callback types
USBCameraFoundCallback = Callable[[DiscoveredUSBCamera], Awaitable[None]]
USBCameraLostCallback = Callable[[str], Awaitable[None]]  # device_id


class USBCameraScanner:
    """
    Continuously scans for USB camera devices.

    Discovers USB cameras via /dev/video* (Linux) or OpenCV enumeration (Windows/macOS).
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

        if not CV2_AVAILABLE:
            logger.warning("Cannot start USB camera scanner - cv2 not available")
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
        """Synchronous USB camera discovery (runs in thread)."""
        if sys.platform == "linux":
            return self._discover_usb_linux()
        elif sys.platform == "win32":
            return self._discover_usb_windows()
        elif sys.platform == "darwin":
            return self._discover_usb_macos()
        else:
            logger.warning(f"Unsupported platform for USB camera discovery: {sys.platform}")
            return []

    def _discover_usb_linux(self) -> list[DiscoveredUSBCamera]:
        """Discover USB cameras on Linux using /dev/video* and sysfs."""
        cameras: list[DiscoveredUSBCamera] = []
        indices = self._detect_from_dev_nodes()
        ordered = self._prioritize_usb(indices)
        seen_roots: dict[str, int] = {}

        for index in ordered[:self.MAX_USB_DEVICES]:
            dev_path = f"/dev/video{index}"
            device_root = self._device_root(index)
            if device_root is None:
                logger.debug(f"Skipping non-USB video node: /dev/video{index}")
                continue

            root_key = str(device_root)
            if root_key in seen_roots:
                logger.debug(
                    f"Skipping duplicate USB node /dev/video{index} for device "
                    f"{device_root.name} (already using /dev/video{seen_roots[root_key]})"
                )
                continue
            seen_roots[root_key] = index

            base_name = self._read_sysfs_name(index) or f"video{index}"
            friendly = self._format_friendly_name(base_name, device_root.name)
            stable_id = self._stable_usb_id(device_root)

            cameras.append(DiscoveredUSBCamera(
                device_id=f"usb:{stable_id}",
                stable_id=stable_id,
                dev_path=dev_path,
                friendly_name=friendly,
                hw_model=base_name,  # Use actual sysfs name for model lookup
                location_hint=str(device_root),
            ))

        logger.debug(f"Discovered {len(cameras)} USB cameras on Linux")
        return cameras

    def _discover_usb_windows(self) -> list[DiscoveredUSBCamera]:
        """Discover USB cameras on Windows using OpenCV enumeration."""
        cameras: list[DiscoveredUSBCamera] = []
        for index in range(self.MAX_USB_DEVICES):
            cap = cv2.VideoCapture(index)
            if cap and cap.isOpened():
                cap.release()
                cameras.append(DiscoveredUSBCamera(
                    device_id=f"usb:{index}",
                    stable_id=str(index),
                    dev_path=str(index),
                    friendly_name=f"USB Camera {index}",
                    hw_model="USB Camera",
                    location_hint=None,
                ))
                logger.debug(f"Discovered Windows USB camera at index {index}")
            else:
                if cap:
                    cap.release()
                break
        logger.debug(f"Discovered {len(cameras)} USB cameras on Windows")
        return cameras

    def _discover_usb_macos(self) -> list[DiscoveredUSBCamera]:
        """Discover USB cameras on macOS using OpenCV enumeration."""
        cameras: list[DiscoveredUSBCamera] = []
        for index in range(self.MAX_USB_DEVICES):
            cap = cv2.VideoCapture(index)
            if cap and cap.isOpened():
                cap.release()
                cameras.append(DiscoveredUSBCamera(
                    device_id=f"usb:{index}",
                    stable_id=str(index),
                    dev_path=str(index),
                    friendly_name=f"USB Camera {index}",
                    hw_model="USB Camera",
                    location_hint=None,
                ))
                logger.debug(f"Discovered macOS USB camera at index {index}")
            else:
                if cap:
                    cap.release()
                break
        logger.debug(f"Discovered {len(cameras)} USB cameras on macOS")
        return cameras

    # Linux-specific helpers

    def _detect_from_dev_nodes(self) -> list[int]:
        """Gather numeric indices from /dev/video*."""
        candidates = sorted(glob.glob("/dev/video*"))
        indices: list[int] = []
        for path in candidates:
            try:
                index = int(Path(path).name.replace("video", ""))
            except ValueError:
                continue
            indices.append(index)
        if not indices:
            indices = list(range(2))  # best-effort fallback probe set
        return sorted(indices)

    def _prioritize_usb(self, indices: list[int]) -> list[int]:
        """Order indices with USB-backed devices first."""
        usb_indices = [idx for idx in indices if self._is_usb(idx)]
        non_usb = [idx for idx in indices if idx not in usb_indices]
        return usb_indices + non_usb

    def _is_usb(self, index: int) -> bool:
        return self._device_root(index) is not None

    def _device_root(self, index: int) -> Optional[Path]:
        """Return the physical USB device root for a /dev/video index."""
        try:
            device_link = Path(f"/sys/class/video4linux/video{index}/device")
            resolved = device_link.resolve()
            if not any("usb" in part for part in resolved.parts):
                return None
            # Interface nodes look like "1-2:1.0"; trim to the device root ("1-2").
            return resolved.parent if ":" in resolved.name else resolved
        except Exception:
            return None

    def _read_sysfs_name(self, index: int) -> Optional[str]:
        sys_name = Path(f"/sys/class/video4linux/video{index}/name")
        try:
            if sys_name.exists():
                text = sys_name.read_text(encoding="utf-8").strip()
                return text or None
        except Exception:
            return None
        return None

    def _stable_usb_id(self, device_root: Path) -> str:
        """Build a stable identifier from the USB bus/port path."""
        bus = device_root.parent.name if device_root.parent and device_root.parent.name.startswith("usb") else ""
        prefix = f"{bus}-" if bus else ""
        return f"{prefix}{device_root.name}"

    def _format_friendly_name(self, base_name: str, port_label: str) -> str:
        label = port_label.replace(":", "-") if port_label else ""
        return f"USB:{base_name} [{label}]" if label else f"USB:{base_name}"

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
