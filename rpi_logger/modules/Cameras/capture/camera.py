"""Camera capture using OpenCV."""

import os
import sys

# Disable MSMF hardware transforms on Windows to fix slow camera initialization.
# See: https://github.com/opencv/opencv/issues/17687
if sys.platform == "win32":
    os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

import cv2
import logging
import threading
import time
from typing import Optional

from .frame import CapturedFrame
from .ring_buffer import FrameRingBuffer

logger = logging.getLogger(__name__)


class Camera:
    """Camera capture using OpenCV.

    Captures at hardware speed configured via fps_hint.
    All frames are recorded without rate limiting.
    """

    def __init__(
        self,
        device: int | str,
        resolution: tuple[int, int],
        fps_hint: float,
        buffer: FrameRingBuffer,
    ):
        """Initialize camera.

        Args:
            device: Camera device index or path
            resolution: Requested resolution (width, height)
            fps_hint: Hint to hardware (not enforced)
            buffer: Ring buffer for captured frames
        """
        self._device = device
        self._resolution = resolution
        self._fps_hint = fps_hint
        self._buffer = buffer

        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._frame_number = 0

        # Measured values (updated continuously)
        self._hardware_fps = 0.0
        self._actual_resolution = resolution

    def open(self) -> bool:
        """Open camera and configure. Returns True on success."""
        device = self._device
        if isinstance(device, str) and device.isdigit():
            device = int(device)

        # Log MSMF HW transforms setting for diagnostics
        hw_transforms = os.environ.get("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "not set")
        logger.debug("Opening camera %s (MSMF_HW_TRANSFORMS=%s)", device, hw_transforms)

        # Explicitly select backend to avoid "DSHOW can't capture by index" warnings.
        # On Windows, use MSMF which gets better FPS than DSHOW.
        # DSHOW often ignores MJPG codec and gets stuck at lower FPS.
        start_time = time.time()
        if sys.platform == "win32":
            self._cap = cv2.VideoCapture(device, cv2.CAP_MSMF)
        else:
            self._cap = cv2.VideoCapture(device)
        elapsed = time.time() - start_time
        logger.debug("cv2.VideoCapture(%s) took %.2f seconds", device, elapsed)

        if not self._cap or not self._cap.isOpened():
            logger.error("Failed to open camera: %s", self._device)
            return False

        # Try MJPG for better FPS on most USB cameras
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])
        self._cap.set(cv2.CAP_PROP_FPS, self._fps_hint)

        # Reduce internal buffer to minimize latency
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Read actual values
        self._actual_resolution = (
            int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

        fourcc_code = int(self._cap.get(cv2.CAP_PROP_FOURCC))
        fourcc_str = "".join([chr((fourcc_code >> 8 * i) & 0xFF) for i in range(4)])

        logger.info(
            "Camera opened: device=%s, resolution=%dx%d, fps_hint=%.1f, fourcc=%s",
            self._device,
            *self._actual_resolution,
            self._fps_hint,
            fourcc_str,
        )
        return True

    def start(self) -> None:
        """Start capture thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.debug("Capture thread started")

    def stop(self) -> None:
        """Stop capture thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.debug("Capture thread stopped")

    def close(self) -> None:
        """Release camera resources."""
        self.stop()
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("Camera closed")

    def _capture_loop(self) -> None:
        """Capture thread - runs at hardware speed, no throttling."""
        intervals: list[float] = []
        last_time = time.monotonic()

        logger.debug("Capture loop started")

        while self._running and self._cap and self._cap.isOpened():
            ret, frame_data = self._cap.read()
            if not ret or frame_data is None:
                time.sleep(0.001)
                continue

            now = time.monotonic()
            self._frame_number += 1

            # Track hardware FPS (rolling window of last 30)
            intervals.append(now - last_time)
            if len(intervals) > 30:
                intervals.pop(0)
            if len(intervals) >= 3:
                avg = sum(intervals) / len(intervals)
                self._hardware_fps = 1.0 / avg if avg > 0 else 0.0
            last_time = now

            frame = CapturedFrame(
                data=frame_data,
                frame_number=self._frame_number,
                monotonic_time=time.perf_counter(),
                wall_time=time.time(),
                size=(frame_data.shape[1], frame_data.shape[0]),
            )
            self._buffer.put(frame)

        logger.debug(
            "Capture loop ended: frames=%d, hardware_fps=%.1f",
            self._frame_number,
            self._hardware_fps,
        )

    @property
    def hardware_fps(self) -> float:
        """Actual measured hardware FPS."""
        return self._hardware_fps

    @property
    def resolution(self) -> tuple[int, int]:
        """Actual camera resolution."""
        return self._actual_resolution

    @property
    def frame_count(self) -> int:
        """Total frames captured."""
        return self._frame_number

    @property
    def is_running(self) -> bool:
        """True if capture thread is running."""
        return self._running


# Backwards compatibility alias
USBCamera = Camera
