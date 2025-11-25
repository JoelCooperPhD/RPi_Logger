"""USB camera backend using OpenCV for frame capture."""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CapabilityMode, CameraCapabilities
from rpi_logger.modules.Cameras.runtime.discovery.capabilities import build_capabilities


class DeviceLost(Exception):
    """Raised when the USB device disappears mid-capture."""


@dataclass(slots=True)
class USBFrame:
    data: np.ndarray
    timestamp: float  # monotonic seconds
    frame_number: int
    monotonic_ns: int
    sensor_timestamp_ns: Optional[int]
    wall_time: float
    wait_ms: float = 0.0
    color_format: str = "bgr"
    storage_queue_drops: int = 0


class USBHandle:
    """Async frame reader for a USB device."""

    def __init__(self, dev_path: str, mode: CapabilityMode, *, logger: LoggerLike = None) -> None:
        self.dev_path = dev_path
        self.mode = mode
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._cap = self._open_capture()
        self._frame_number = 0
        self._stopped = False
        self._running = False
        self._error: Optional[Exception] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue] = None
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="usbcam"
        )
        self._producer_future: Optional[concurrent.futures.Future] = None

    def _open_capture(self):
        """Prefer V4L2 backend on Linux, fallback to default."""

        import sys
        device_id = int(self.dev_path) if self.dev_path.isdigit() else self.dev_path

        default_backend = getattr(cv2, "CAP_V4L2", None) if sys.platform == "linux" else None
        backends = []
        if default_backend is not None:
            backends.append(default_backend)
        backends.append(None)  # OpenCV default

        last_error = None
        for backend in backends:
            try:
                cap = cv2.VideoCapture(device_id, backend) if backend is not None else cv2.VideoCapture(device_id)
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
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=2)
        self._error = None
        await self._loop.run_in_executor(self._executor, self._configure)
        self._running = True
        self._producer_future = self._executor.submit(self._producer_loop)

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
        target_fps = self.mode.fps if hasattr(self.mode, 'fps') and self.mode.fps else 30.0
        self._cap.set(cv2.CAP_PROP_FPS, target_fps)

    async def read_frame(self) -> USBFrame:
        queue = self._queue
        if queue is None:
            queue = asyncio.Queue()
            self._queue = queue
        frame, wait_ms, error = await queue.get()
        if frame is None:
            if error:
                raise error
            raise DeviceLost(f"USB device {self.dev_path} stopped")
        self._frame_number += 1
        monotonic_ns = time.monotonic_ns()
        wall_ts = time.time()
        return USBFrame(
            data=frame,
            timestamp=monotonic_ns / 1_000_000_000,
            frame_number=self._frame_number,
            monotonic_ns=monotonic_ns,
            sensor_timestamp_ns=None,
            wall_time=wall_ts,
            wait_ms=wait_ms,
        )

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._running = False
        loop = self._loop or asyncio.get_running_loop()
        if self._queue:
            try:
                loop.call_soon_threadsafe(self._offer_frame, None, 0.0, None, True)
            except Exception:
                pass
        if self._cap:
            await loop.run_in_executor(self._executor, self._release)
            self._cap = None
        self._shutdown_executor()

    def is_alive(self) -> bool:
        return bool(self._cap and self._cap.isOpened())

    # ------------------------------------------------------------------ producer

    def _producer_loop(self) -> None:
        while self._running:
            wait_start = time.perf_counter()
            success, frame = self._cap.read() if self._cap else (False, None)
            wait_ms = (time.perf_counter() - wait_start) * 1000.0
            if not success:
                self._error = DeviceLost(f"USB device {self.dev_path} lost or failed to read")
                self._running = False
                loop = self._loop
                if loop:
                    try:
                        loop.call_soon_threadsafe(self._offer_frame, None, wait_ms, self._error, True)
                    except Exception:
                        pass
                break
            loop = self._loop
            if not loop:
                continue
            try:
                loop.call_soon_threadsafe(self._offer_frame, frame, wait_ms, None, False)
            except Exception:
                pass
        loop = self._loop
        if loop:
            try:
                loop.call_soon_threadsafe(self._offer_frame, None, 0.0, self._error, True)
            except Exception:
                pass

    def _offer_frame(self, frame, wait_ms: float, error: Optional[Exception], sentinel: bool = False) -> None:
        queue = self._queue
        if not queue:
            return
        if sentinel:
            try:
                queue.put_nowait((None, wait_ms, error))
            except Exception:
                pass
            return
        if queue.full():
            try:
                queue.get_nowait()
            except Exception:
                pass
        try:
            queue.put_nowait((frame, wait_ms, None))
        except Exception:
            pass

    def _release(self) -> None:
        try:
            if self._cap:
                self._cap.release()
        except Exception:
            self._logger.debug("USB cap release failed", exc_info=True)

    def _shutdown_executor(self) -> None:
        if self._executor:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass
            self._executor = None


async def probe(dev_path: str, *, logger: LoggerLike = None) -> Optional[CameraCapabilities]:
    """Probe device modes in a thread."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    return await asyncio.to_thread(_probe_sync, dev_path, log)


def _probe_sync(dev_path: str, log) -> Optional[CameraCapabilities]:
    import sys
    device_id = int(dev_path) if dev_path.isdigit() else dev_path

    cap = None
    default_backend = getattr(cv2, "CAP_V4L2", None) if sys.platform == "linux" else None
    backends = [b for b in (default_backend, None)]
    for backend in backends:
        try:
            cap = cv2.VideoCapture(device_id, backend) if backend is not None else cv2.VideoCapture(device_id)
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
