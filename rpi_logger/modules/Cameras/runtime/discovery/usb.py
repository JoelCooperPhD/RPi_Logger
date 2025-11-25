"""USB discovery helpers."""

from __future__ import annotations

import asyncio
import glob
import os
import sys
from pathlib import Path
from typing import List, Optional

import cv2

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CameraDescriptor, CameraId
from .capabilities import build_capabilities


def discover_usb_devices(logger: LoggerLike = None, max_devices: int = 16) -> List[CameraDescriptor]:
    """List available USB cameras using platform-specific discovery."""

    log = ensure_structured_logger(logger, fallback_name=__name__)

    if sys.platform == "linux":
        return _discover_linux(log, max_devices)
    elif sys.platform == "win32":
        return _discover_windows(log, max_devices)
    elif sys.platform == "darwin":
        return _discover_macos(log, max_devices)
    else:
        log.warning("Unsupported platform for USB camera discovery: %s", sys.platform)
        return []


def _discover_linux(log, max_devices: int) -> List[CameraDescriptor]:
    """Discover USB cameras on Linux using /dev/video* and sysfs."""

    descriptors: list[CameraDescriptor] = []
    indices = _detect_from_dev_nodes()
    ordered = _prioritize_usb(indices)
    seen_roots: dict[str, int] = {}

    for index in ordered[:max_devices]:
        dev_path = f"/dev/video{index}"
        device_root = _device_root(index)
        if device_root is None:
            log.debug("Skipping non-USB video node: /dev/video%s", index)
            continue

        root_key = str(device_root)
        if root_key in seen_roots:
            log.debug(
                "Skipping duplicate USB node /dev/video%s for device %s (already using /dev/video%s)",
                index,
                device_root.name,
                seen_roots[root_key],
            )
            continue
        seen_roots[root_key] = index

        base_name = _read_sysfs_name(index) or os.path.basename(dev_path)
        friendly = _format_friendly_name(base_name, device_root.name)
        stable_id = _stable_usb_id(device_root)
        camera_id = CameraId(
            backend="usb",
            stable_id=stable_id,
            dev_path=dev_path,
            friendly_name=friendly,
        )
        descriptors.append(CameraDescriptor(camera_id=camera_id, hw_model="USB Camera", location_hint=str(device_root)))
    log.debug(
        "Discovered %d USB devices (ordered=%s roots=%s)",
        len(descriptors),
        ordered[:max_devices],
        sorted(seen_roots.values()),
    )
    return descriptors


def _discover_windows(log, max_devices: int) -> List[CameraDescriptor]:
    """Discover USB cameras on Windows using OpenCV enumeration."""

    descriptors: list[CameraDescriptor] = []
    for index in range(max_devices):
        cap = cv2.VideoCapture(index)
        if cap and cap.isOpened():
            cap.release()
            camera_id = CameraId(
                backend="usb",
                stable_id=str(index),
                dev_path=str(index),
                friendly_name=f"USB Camera {index}",
            )
            descriptors.append(CameraDescriptor(camera_id=camera_id, hw_model="USB Camera", location_hint=None))
            log.debug("Discovered Windows USB camera at index %d", index)
        else:
            if cap:
                cap.release()
            break
    log.debug("Discovered %d USB cameras on Windows", len(descriptors))
    return descriptors


def _discover_macos(log, max_devices: int) -> List[CameraDescriptor]:
    """Discover USB cameras on macOS using OpenCV enumeration."""

    descriptors: list[CameraDescriptor] = []
    for index in range(max_devices):
        cap = cv2.VideoCapture(index)
        if cap and cap.isOpened():
            cap.release()
            camera_id = CameraId(
                backend="usb",
                stable_id=str(index),
                dev_path=str(index),
                friendly_name=f"USB Camera {index}",
            )
            descriptors.append(CameraDescriptor(camera_id=camera_id, hw_model="USB Camera", location_hint=None))
            log.debug("Discovered macOS USB camera at index %d", index)
        else:
            if cap:
                cap.release()
            break
    log.debug("Discovered %d USB cameras on macOS", len(descriptors))
    return descriptors


async def probe_usb_capabilities(dev_path: str, *, logger: LoggerLike = None):
    """Probe capabilities for a USB camera using OpenCV in a thread."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    return await asyncio.to_thread(_probe_usb_sync, dev_path, log)


def _probe_usb_sync(dev_path: str, log) -> Optional[object]:
    device_id = int(dev_path) if dev_path.isdigit() else dev_path
    cap = cv2.VideoCapture(device_id)
    if not cap.isOpened():
        log.warning("Unable to open USB device %s", dev_path)
        return None

    modes = []
    try:
        widths = [320, 640, 800, 1280, 1920]
        heights = [240, 480, 600, 720, 1080]
        fps_options = [15, 24, 30, 60]
        for w, h in zip(widths, heights):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            for fps in fps_options:
                cap.set(cv2.CAP_PROP_FPS, fps)
                actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                actual_fps = float(cap.get(cv2.CAP_PROP_FPS) or fps)
                if actual_w and actual_h:
                    modes.append({"size": (actual_w, actual_h), "fps": actual_fps, "pixel_format": "MJPEG"})
    finally:
        cap.release()

    capabilities = build_capabilities(modes)
    return capabilities


def _detect_from_dev_nodes() -> list[int]:
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


def _prioritize_usb(indices: list[int]) -> list[int]:
    """Order indices with USB-backed devices first."""

    usb_indices = [idx for idx in indices if _is_usb(idx)]
    non_usb = [idx for idx in indices if idx not in usb_indices]
    return usb_indices + non_usb


def _is_usb(index: int) -> bool:
    return _device_root(index) is not None


def _device_root(index: int) -> Optional[Path]:
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


def _read_sysfs_name(index: int) -> Optional[str]:
    sys_name = Path(f"/sys/class/video4linux/video{index}/name")
    try:
        if sys_name.exists():
            text = sys_name.read_text(encoding="utf-8").strip()
            return text or None
    except Exception:
        return None
    return None


def _stable_usb_id(device_root: Path) -> str:
    """Build a stable identifier from the USB bus/port path."""

    bus = device_root.parent.name if device_root.parent and device_root.parent.name.startswith("usb") else ""
    prefix = f"{bus}-" if bus else ""
    return f"{prefix}{device_root.name}"


def _format_friendly_name(base_name: str, port_label: str) -> str:
    label = port_label.replace(":", "-") if port_label else ""
    return f"USB:{base_name} [{label}]" if label else f"USB:{base_name}"


__all__ = ["discover_usb_devices", "probe_usb_capabilities"]
