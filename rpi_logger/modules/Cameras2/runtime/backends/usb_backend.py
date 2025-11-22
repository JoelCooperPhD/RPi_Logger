"""USB camera backend using OpenCV for frame capture."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras2.runtime import CapabilityMode, CameraCapabilities
from rpi_logger.modules.Cameras2.runtime.discovery.capabilities import build_capabilities


class DeviceLost(Exception):
    """Raised when the USB device disappears mid-capture."""


@dataclass(slots=True)
class USBFrame:
    data: np.ndarray
    timestamp: float
    frame_number: int
    wait_ms: float = 0.0


class USBHandle:
    """Async frame reader for a USB device."""

    def __init__(self, dev_path: str, mode: CapabilityMode, *, logger: LoggerLike = None) -> None:
        self.dev_path = dev_path
        self.mode = mode
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._cap = self._open_capture()
        self._frame_number = 0
        self._stopped = False

    def _open_capture(self):
        """Prefer V4L2 backend then fallback to default."""

        default_backend = getattr(cv2, "CAP_V4L2", None)
        backends = []
        if default_backend is not None:
            backends.append(default_backend)
        backends.append(None)  # OpenCV default

        last_error = None
        for backend in backends:
            try:
                cap = cv2.VideoCapture(self.dev_path, backend) if backend is not None else cv2.VideoCapture(self.dev_path)
            except Exception as exc:  # pragma: no cover - defensive
                last_error = str(exc)
                continue
            if cap and cap.isOpened():
                return cap
            try:
                if cap:
                    cap.release()
            except Exception:
                pass

        self._logger.warning("Unable to open USB device %s (backend error: %s)", self.dev_path, last_error)
        return None

    async def start(self) -> None:
        await asyncio.to_thread(self._configure)

    def _configure(self) -> None:
        if not self._cap:
            raise DeviceLost(f"USB device {self.dev_path} could not be opened")
        # Prefer MJPEG to avoid YUYV color issues on some UVC cams.
        try:
            fourcc = getattr(cv2, "VideoWriter_fourcc", lambda *args: 0)("M", "J", "P", "G")
            self._cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.mode.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.mode.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.mode.fps)

    async def read_frame(self) -> USBFrame:
        wait_start = time.perf_counter()
        success, frame = await asyncio.to_thread(self._cap.read)
        wait_ms = (time.perf_counter() - wait_start) * 1000.0
        if not success:
            raise DeviceLost(f"USB device {self.dev_path} lost or failed to read")
        self._frame_number += 1
        ts = time.time()
        return USBFrame(data=frame, timestamp=ts, frame_number=self._frame_number, wait_ms=wait_ms)

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self._cap:
            await asyncio.to_thread(self._cap.release)
            self._cap = None

    def is_alive(self) -> bool:
        return bool(self._cap and self._cap.isOpened())


async def probe(dev_path: str, *, logger: LoggerLike = None) -> Optional[CameraCapabilities]:
    """Probe device modes in a thread."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    return await asyncio.to_thread(_probe_sync, dev_path, log)


def _probe_sync(dev_path: str, log) -> Optional[CameraCapabilities]:
    cap = None
    default_backend = getattr(cv2, "CAP_V4L2", None)
    backends = [b for b in (default_backend, None)]
    for backend in backends:
        try:
            cap = cv2.VideoCapture(dev_path, backend) if backend is not None else cv2.VideoCapture(dev_path)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("VideoCapture open failed for %s backend=%s: %s", dev_path, backend, exc)
            cap = None
            continue
        if cap and cap.isOpened():
            break
        if cap:
            cap.release()
            cap = None

    if not cap or not cap.isOpened():
        log.warning("Unable to open USB device %s", dev_path)
        return None
    modes = []
    try:
        try:
            fourcc = getattr(cv2, "VideoWriter_fourcc", lambda *args: 0)("M", "J", "P", "G")
            cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass
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
    return build_capabilities(modes)


async def open_device(dev_path: str, mode: CapabilityMode, *, logger: LoggerLike = None) -> USBHandle:
    handle = USBHandle(dev_path, mode, logger=logger)
    await handle.start()
    if not handle.is_alive():
        raise DeviceLost(f"USB device {dev_path} failed to start")
    return handle


__all__ = ["USBHandle", "USBFrame", "DeviceLost", "probe", "open_device"]
