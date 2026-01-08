from pathlib import Path
import asyncio
import subprocess
from typing import BinaryIO
import cv2
import numpy as np

from capture.frame import CapturedFrame


class VideoEncoder:
    def __init__(
        self,
        output_path: Path,
        resolution: tuple[int, int],
        fps: int,
        quality: int = 85
    ):
        self._output_path = output_path
        self._resolution = resolution
        self._fps = fps
        self._quality = quality
        self._writer: cv2.VideoWriter | None = None
        self._frame_count = 0
        self._running = False

    async def start(self) -> None:
        self._writer = await asyncio.to_thread(self._create_writer)
        self._frame_count = 0
        self._running = True

    def _create_writer(self) -> cv2.VideoWriter:
        fourcc = cv2.VideoWriter.fourcc(*'MJPG')
        return cv2.VideoWriter(
            str(self._output_path),
            fourcc,
            self._fps,
            self._resolution,
        )

    async def write_frame(self, frame: CapturedFrame) -> None:
        if not self._writer or not self._running:
            return

        if frame.color_format == "yuv420":
            bgr = await asyncio.to_thread(self._convert_yuv_to_bgr, frame.data, frame.size)
        else:
            bgr = frame.data

        await asyncio.to_thread(self._writer.write, bgr)
        self._frame_count += 1

    def _convert_yuv_to_bgr(self, yuv_data: np.ndarray, size: tuple[int, int]) -> np.ndarray:
        width, height = size
        yuv_height = height + height // 2
        yuv = yuv_data.reshape((yuv_height, width))
        return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)

    async def stop(self) -> None:
        self._running = False
        if self._writer:
            await asyncio.to_thread(self._writer.release)
            self._writer = None

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def output_path(self) -> Path:
        return self._output_path

    @property
    def is_running(self) -> bool:
        return self._running
