import asyncio
import threading
import time
from typing import AsyncIterator, Callable, Optional

import numpy as np

from .frame import CapturedFrame
from .frame_buffer import FrameBuffer


class USBSource:
    def __init__(
        self,
        device: int | str,
        resolution: tuple[int, int] = (640, 480),
        fps: float = 30.0,
        buffer_capacity: int = 8,
    ):
        self._device = device
        self._resolution = resolution
        self._fps = fps
        self._buffer = FrameBuffer(capacity=buffer_capacity)
        self._cap = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._frame_number = 0
        self._sequence_number = 0
        self._on_error: Optional[Callable[[str], None]] = None

    def set_error_callback(self, callback: Callable[[str], None]) -> None:
        self._on_error = callback

    def open(self) -> bool:
        try:
            import cv2
        except ImportError:
            if self._on_error:
                self._on_error("OpenCV (cv2) not available")
            return False

        self._cap = cv2.VideoCapture(self._device)
        if not self._cap.isOpened():
            if self._on_error:
                self._on_error(f"Failed to open {self._device}")
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._resolution = (actual_w, actual_h)

        return True

    def close(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._cap:
            self._cap.release()
            self._cap = None
        self._buffer.stop()
        self._buffer.clear()

    def start_capture(self) -> None:
        if self._running:
            return
        if not self._cap or not self._cap.isOpened():
            if not self.open():
                return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop_capture(self) -> None:
        self._running = False
        self._buffer.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _capture_loop(self) -> None:
        while self._running and self._cap and self._cap.isOpened():
            ret, frame_data = self._cap.read()
            if not ret or frame_data is None:
                time.sleep(0.001)
                continue

            mono_ns = time.monotonic_ns()
            wall_time = time.time()

            self._frame_number += 1
            self._sequence_number += 1

            frame = CapturedFrame(
                data=frame_data,
                frame_number=self._frame_number,
                capture_timestamp_ns=mono_ns,
                monotonic_ns=mono_ns,
                wall_time=wall_time,
                color_format="BGR",
                size=(frame_data.shape[1], frame_data.shape[0]),
                sequence_number=self._sequence_number,
            )

            self._buffer.put_overwrite(frame)

    async def frames(self) -> AsyncIterator[CapturedFrame]:
        async for frame in self._buffer.frames():
            yield frame

    async def get_frame(self) -> Optional[CapturedFrame]:
        return await self._buffer.get()

    @property
    def resolution(self) -> tuple[int, int]:
        return self._resolution

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def frame_count(self) -> int:
        return self._frame_number

    @property
    def drops(self) -> int:
        return self._buffer.drops

    @property
    def is_running(self) -> bool:
        return self._running

    def configure(
        self,
        resolution: Optional[tuple[int, int]] = None,
        fps: Optional[float] = None,
    ) -> bool:
        was_running = self._running
        if was_running:
            self.stop_capture()

        if resolution:
            self._resolution = resolution
        if fps:
            self._fps = fps

        if self._cap and self._cap.isOpened():
            import cv2
            if resolution:
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
                actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self._resolution = (actual_w, actual_h)
            if fps:
                self._cap.set(cv2.CAP_PROP_FPS, fps)

        if was_running:
            self.start_capture()

        return True
