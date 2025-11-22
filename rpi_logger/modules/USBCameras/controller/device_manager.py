"""Discovery helpers for USB cameras."""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Iterable, List, Optional

from ..io.capture import USBCameraInfo
from rpi_logger.core.logging_utils import ensure_structured_logger


class USBCameraDiscovery:
    """Enumerates USB cameras based on /dev/video* entries."""

    def __init__(self, logger) -> None:
        self.logger = ensure_structured_logger(
            logger,
            component="USBCameraDiscovery",
            fallback_name=f"{__name__}.USBCameraDiscovery",
        )

    @staticmethod
    def parse_indices(raw: Optional[str]) -> list[int]:
        if not raw:
            return []
        indices: list[int] = []
        for part in raw.split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            try:
                indices.append(int(cleaned))
            except ValueError:
                continue
        return indices

    def discover(self, *, requested: Optional[Iterable[int]], max_devices: int) -> List[USBCameraInfo]:
        self.logger.debug("Discovering USB cameras | requested=%s max=%s", list(requested or []), max_devices)
        if requested:
            indices = list(dict.fromkeys(int(idx) for idx in requested if idx >= 0))
        else:
            indices = self._prioritize_usb(self._detect_from_dev_nodes())

        camera_infos: list[USBCameraInfo] = []
        for index in indices[:max_devices]:
            path = f"/dev/video{index}"
            name = self._read_sysfs_name(index) or f"USB Camera {index}"
            camera_infos.append(USBCameraInfo(index=index, path=path, name=name))
        self.logger.info("Discovered %d candidate USB cameras: %s", len(camera_infos), indices)
        return camera_infos

    def _detect_from_dev_nodes(self) -> list[int]:
        candidates = sorted(glob.glob("/dev/video*"))
        indices: list[int] = []
        for path in candidates:
            try:
                index = int(Path(path).name.replace("video", ""))
            except ValueError:
                continue
            indices.append(index)
        if not indices:
            indices = list(range(2))  # fallback: probe 0..1
        indices = sorted(indices)
        self.logger.debug("Detected dev nodes: %s", indices)
        return indices

    def _is_usb(self, index: int) -> bool:
        try:
            device_link = Path(f"/sys/class/video4linux/video{index}/device")
            if not device_link.exists():
                return False
            resolved = device_link.resolve()
            return "usb" in str(resolved)
        except Exception:
            return False

    def _prioritize_usb(self, indices: list[int]) -> list[int]:
        """Return indices with USB-backed devices first, preserving order within groups."""
        usb_indices = [idx for idx in indices if self._is_usb(idx)]
        non_usb = [idx for idx in indices if idx not in usb_indices]
        ordered = usb_indices + non_usb
        self.logger.debug("USB-prioritized order: %s", ordered)
        return ordered

    def _read_sysfs_name(self, index: int) -> Optional[str]:
        """Best-effort friendly name from /sys/class/video4linux."""

        sys_name = Path(f"/sys/class/video4linux/video{index}/name")
        try:
            if sys_name.exists():
                text = sys_name.read_text(encoding="utf-8").strip()
                return text or None
        except Exception:
            return None
        return None


__all__ = ["USBCameraDiscovery"]
