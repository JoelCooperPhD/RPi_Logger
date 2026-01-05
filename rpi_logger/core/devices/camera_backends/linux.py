"""
Linux camera discovery backend.

Discovers USB cameras on Linux using /dev/video* nodes and sysfs enumeration.
This provides detailed device information including real device names from
the kernel driver and stable USB bus/port identifiers.

Also probes for audio siblings (built-in microphones) on the same USB device.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

import glob
from pathlib import Path
from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger

from .base import AudioSiblingInfo, DiscoveredUSBCamera
from ..physical_id import USBPhysicalIdResolver

logger = get_module_logger("LinuxCameraBackend")

# Try to import OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("cv2 not available - camera discovery disabled")

# Try to import sounddevice for audio sibling detection
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    logger.debug("sounddevice not available - audio sibling detection disabled")


class LinuxCameraBackend:
    """Linux camera discovery using sysfs and OpenCV.

    This backend provides rich device information by reading from:
    - /dev/video* nodes for device enumeration
    - /sys/class/video4linux/*/name for device names
    - USB sysfs paths for stable device identification
    """

    def discover_cameras(self, max_devices: int = 16) -> list[DiscoveredUSBCamera]:
        """Discover USB cameras on Linux using /dev/video* and sysfs."""
        if not CV2_AVAILABLE:
            logger.debug("OpenCV not available, skipping camera discovery")
            return []

        cameras: list[DiscoveredUSBCamera] = []
        indices = self._detect_from_dev_nodes()
        ordered = self._prioritize_usb(indices)
        seen_roots: dict[str, int] = {}

        for index in ordered[:max_devices]:
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

            # Probe for audio sibling (built-in microphone)
            audio_sibling = None
            if SOUNDDEVICE_AVAILABLE:
                sibling_info = USBPhysicalIdResolver.find_audio_sibling_for_video(dev_path)
                if sibling_info:
                    audio_sibling = AudioSiblingInfo(
                        sounddevice_index=sibling_info["sounddevice_index"],
                        alsa_card=sibling_info.get("alsa_card"),
                        channels=sibling_info.get("channels", 2),
                        sample_rate=sibling_info.get("sample_rate", 48000.0),
                        name=sibling_info.get("name", ""),
                    )
                    logger.info(
                        f"Found audio sibling for {base_name}: {audio_sibling.name} "
                        f"(index={audio_sibling.sounddevice_index})"
                    )

            cameras.append(DiscoveredUSBCamera(
                device_id=f"usb:{stable_id}",
                stable_id=stable_id,
                dev_path=dev_path,
                friendly_name=friendly,
                hw_model=base_name,
                location_hint=str(device_root),
                usb_bus_path=stable_id,
                audio_sibling=audio_sibling,
            ))

        logger.debug(f"Discovered {len(cameras)} USB cameras on Linux")
        return cameras

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
        """Check if a video device is USB-backed."""
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
        """Read the device name from sysfs."""
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
        """Format a user-friendly display name."""
        label = port_label.replace(":", "-") if port_label else ""
        return f"USB:{base_name} [{label}]" if label else f"USB:{base_name}"


__all__ = ["LinuxCameraBackend"]
