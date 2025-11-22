"""USB discovery helpers."""

from __future__ import annotations

import asyncio
import glob
import os
from pathlib import Path
from typing import Iterable, List, Optional

import cv2

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras2.runtime import CameraDescriptor, CameraId
from .capabilities import build_capabilities


def discover_usb_devices(logger: LoggerLike = None, max_devices: int = 16) -> List[CameraDescriptor]:
    """List available /dev/video* devices, preferring real USB nodes."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    descriptors: list[CameraDescriptor] = []
    indices = _detect_from_dev_nodes()
    ordered = _prioritize_usb(indices)

    for index in ordered[:max_devices]:
        dev_path = f"/dev/video{index}"
        base_name = _read_sysfs_name(index) or os.path.basename(dev_path)
        friendly = f"USB:{base_name}"
        if not _is_usb(index):
            log.debug("Skipping non-USB video node: /dev/video%s (%s)", index, friendly)
            continue
        camera_id = CameraId(
            backend="usb",
            stable_id=dev_path,
            dev_path=dev_path,
            friendly_name=friendly,
        )
        descriptors.append(CameraDescriptor(camera_id=camera_id, hw_model="USB Camera", location_hint=dev_path))
    log.debug("Discovered %d USB devices (ordered=%s)", len(descriptors), ordered[:max_devices])
    return descriptors


async def probe_usb_capabilities(dev_path: str, *, logger: LoggerLike = None):
    """Probe capabilities for a USB camera using OpenCV in a thread."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    return await asyncio.to_thread(_probe_usb_sync, dev_path, log)


def _probe_usb_sync(dev_path: str, log) -> Optional[object]:
    cap = cv2.VideoCapture(dev_path)
    if not cap.isOpened():
        log.warning("Unable to open USB device %s", dev_path)
        return None

    modes = []
    # Minimal probing; deeper mode enumeration would use v4l2 controls.
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
    try:
        device_link = Path(f"/sys/class/video4linux/video{index}/device")
        if not device_link.exists():
            return False
        resolved = device_link.resolve()
        return "usb" in str(resolved)
    except Exception:
        return False


def _read_sysfs_name(index: int) -> Optional[str]:
    sys_name = Path(f"/sys/class/video4linux/video{index}/name")
    try:
        if sys_name.exists():
            text = sys_name.read_text(encoding="utf-8").strip()
            return text or None
    except Exception:
        return None
    return None


__all__ = ["discover_usb_devices", "probe_usb_capabilities"]
