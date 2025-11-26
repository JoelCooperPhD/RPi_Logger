"""
Camera capture abstraction for the worker process.

Provides a unified interface for Picamera2 and USB cameras.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Tuple

import numpy as np

from rpi_logger.modules.Cameras.defaults import DEFAULT_CAPTURE_RESOLUTION, DEFAULT_CAPTURE_FPS
from rpi_logger.modules.Cameras.runtime.backends.picam_color import get_picam_color_format


@dataclass(slots=True)
class CaptureFrame:
    """Unified frame data from any camera backend."""
    data: np.ndarray
    timestamp: float  # monotonic seconds
    frame_number: int
    monotonic_ns: int
    sensor_timestamp_ns: Optional[int]
    wall_time: float
    color_format: str = "bgr"


class CaptureHandle:
    """Abstract base for camera capture."""

    async def start(self) -> None:
        raise NotImplementedError

    async def frames(self) -> AsyncIterator[CaptureFrame]:
        raise NotImplementedError
        yield  # type: ignore

    async def stop(self) -> None:
        raise NotImplementedError


class PicamCapture(CaptureHandle):
    """Picamera2-based capture for Raspberry Pi cameras."""

    def __init__(self, sensor_id: str, resolution: tuple[int, int], fps: float) -> None:
        self._sensor_id = sensor_id
        self._resolution = resolution
        self._fps = fps
        self._cam = None
        self._running = False
        self._frame_number = 0

    async def start(self) -> None:
        import logging
        log = logging.getLogger(__name__)

        cam_num = int(self._sensor_id) if self._sensor_id.isdigit() else 0
        log.info("Opening Picamera2 sensor %s (cam_num=%d)", self._sensor_id, cam_num)

        # Run all blocking Picamera2 operations in thread pool
        await asyncio.to_thread(self._start_sync, cam_num, log)
        self._running = True

    def _start_sync(self, cam_num: int, log) -> None:
        from picamera2 import Picamera2

        try:
            Picamera2.close_camera(cam_num)
        except Exception:
            pass

        log.info("Creating Picamera2 instance...")
        self._cam = Picamera2(camera_num=cam_num)
        log.info("Creating video configuration: %s @ %.1f fps", self._resolution, self._fps)

        config = self._cam.create_video_configuration(
            main={"size": self._resolution, "format": "RGB888"},
            buffer_count=4,
        )
        controls = config.get("controls") or {}
        frame_duration_us = int(1_000_000 / self._fps)
        controls["FrameDurationLimits"] = (frame_duration_us, frame_duration_us)
        config["controls"] = controls

        log.info("Configuring camera...")
        self._cam.configure(config)
        log.info("Starting camera...")
        self._cam.start()
        log.info("Camera started successfully")

    async def frames(self) -> AsyncIterator[CaptureFrame]:
        import contextlib

        while self._running:
            request = await asyncio.to_thread(self._cam.capture_request)
            if request is None:
                continue

            self._frame_number += 1
            monotonic_ns = time.monotonic_ns()
            wall_time = time.time()

            metadata = {}
            frame = None
            try:
                with contextlib.suppress(Exception):
                    metadata = request.get_metadata() or {}
                frame = request.make_array("main")
            finally:
                try:
                    request.release()
                except Exception:
                    pass

            if frame is None:
                continue

            sensor_ts = self._extract_sensor_timestamp(metadata)

            # Color format from picam_color module - see that file for IMX296 bug explanation
            yield CaptureFrame(
                data=frame,
                timestamp=monotonic_ns / 1_000_000_000,
                frame_number=self._frame_number,
                monotonic_ns=monotonic_ns,
                sensor_timestamp_ns=sensor_ts,
                wall_time=wall_time,
                color_format=get_picam_color_format(),
            )

    async def stop(self) -> None:
        self._running = False
        if self._cam:
            try:
                await asyncio.to_thread(self._cam.stop)
            except Exception:
                pass
            try:
                await asyncio.to_thread(self._cam.close)
            except Exception:
                pass
            self._cam = None

    @staticmethod
    def _extract_sensor_timestamp(metadata: dict) -> Optional[int]:
        sensor_ts = metadata.get("SensorTimestamp")
        if isinstance(sensor_ts, (int, float)):
            try:
                return int(sensor_ts)
            except Exception:
                return None
        return None


class USBCapture(CaptureHandle):
    """OpenCV-based capture for USB cameras."""

    def __init__(self, dev_path: str, resolution: tuple[int, int], fps: float) -> None:
        self._dev_path = dev_path
        self._resolution = resolution
        self._fps = fps
        self._cap = None
        self._running = False
        self._frame_number = 0

    async def start(self) -> None:
        import logging
        import sys
        import cv2

        log = logging.getLogger(__name__)
        device_id = int(self._dev_path) if self._dev_path.isdigit() else self._dev_path
        log.info("Opening USB camera: %s", device_id)

        # Prefer V4L2 on Linux
        backend = getattr(cv2, "CAP_V4L2", None) if sys.platform == "linux" else None
        if backend is not None:
            self._cap = cv2.VideoCapture(device_id, backend)
        else:
            self._cap = cv2.VideoCapture(device_id)

        if not self._cap or not self._cap.isOpened():
            raise RuntimeError(f"Failed to open USB camera: {self._dev_path}")

        # Configure MJPEG format and resolution
        try:
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self._cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

        # Disable dynamic framerate (some cameras lower FPS in low light otherwise)
        # This is controlled via v4l2-ctl as OpenCV doesn't expose this property
        if sys.platform == "linux" and isinstance(device_id, str) and device_id.startswith("/dev/video"):
            import subprocess
            try:
                subprocess.run(
                    ["v4l2-ctl", "-d", device_id, "-c", "exposure_dynamic_framerate=0"],
                    capture_output=True, timeout=2.0
                )
                log.debug("Disabled exposure_dynamic_framerate for %s", device_id)
            except Exception as e:
                log.debug("Could not set exposure_dynamic_framerate: %s", e)

        # Read a test frame to verify the camera works (with retry for cameras that need warmup)
        import time as _time
        for attempt in range(3):
            if attempt > 0:
                _time.sleep(0.2)
            success, _ = self._cap.read()
            if success:
                break
            log.debug("USB camera %s test frame attempt %d failed, retrying...", self._dev_path, attempt + 1)
        if not success:
            self._cap.release()
            raise RuntimeError(f"USB camera {self._dev_path} opened but cannot read frames")

        log.info("USB camera opened successfully: %dx%d @ %.1f fps",
                int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                self._cap.get(cv2.CAP_PROP_FPS))
        self._running = True

    async def frames(self) -> AsyncIterator[CaptureFrame]:
        import queue
        frame_queue: queue.Queue = queue.Queue(maxsize=2)

        def capture_thread():
            consecutive_failures = 0
            while self._running:
                success, frame = self._cap.read()
                if not success:
                    consecutive_failures += 1
                    if consecutive_failures >= 10:
                        frame_queue.put(None)
                        return
                    continue
                consecutive_failures = 0
                self._frame_number += 1
                try:
                    frame_queue.put((frame, time.monotonic_ns(), time.time()), timeout=0.1)
                except queue.Full:
                    pass  # Drop frame if consumer is slow
            frame_queue.put(None)

        import threading
        thread = threading.Thread(target=capture_thread, daemon=True)
        thread.start()

        while self._running:
            try:
                item = await asyncio.to_thread(frame_queue.get, timeout=1.0)
            except Exception:
                continue
            if item is None:
                break
            frame, monotonic_ns, wall_time = item
            yield CaptureFrame(
                data=frame,
                timestamp=monotonic_ns / 1_000_000_000,
                frame_number=self._frame_number,
                monotonic_ns=monotonic_ns,
                sensor_timestamp_ns=None,
                wall_time=wall_time,
                color_format="bgr",
            )

    async def stop(self) -> None:
        self._running = False
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None


async def open_capture(
    camera_type: str,
    camera_id: str,
    resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION,
    fps: float = DEFAULT_CAPTURE_FPS,
) -> Tuple[CaptureHandle, dict]:
    """
    Open a camera and return (capture_handle, capabilities).

    Args:
        camera_type: "picam" or "usb"
        camera_id: sensor ID or device path
        resolution: capture resolution (width, height)
        fps: target frame rate

    Returns:
        Tuple of (CaptureHandle, capabilities dict)
    """
    capabilities: dict = {
        "camera_type": camera_type,
        "camera_id": camera_id,
        "resolution": resolution,
        "fps": fps,
    }

    if camera_type == "picam":
        capture = PicamCapture(camera_id, resolution, fps)
    elif camera_type == "usb":
        capture = USBCapture(camera_id, resolution, fps)
    else:
        raise ValueError(f"Unknown camera type: {camera_type}")

    await capture.start()
    return capture, capabilities


__all__ = ["CaptureFrame", "CaptureHandle", "PicamCapture", "USBCapture", "open_capture"]
