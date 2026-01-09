from pathlib import Path
import asyncio

import cv2
import numpy as np

from ..capture.frame import CapturedFrame


class VideoEncoder:
    def __init__(
        self,
        output_path: Path,
        resolution: tuple[int, int],
        fps: int,
        with_audio: bool = False,
    ):
        self._output_path = output_path
        self._resolution = resolution
        self._fps = fps
        self._with_audio = with_audio
        self._writer: cv2.VideoWriter | None = None
        self._frame_count = 0
        self._running = False

    async def start(self) -> None:
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
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

        bgr = frame.data
        if frame.color_format == "RGB":
            bgr = await asyncio.to_thread(cv2.cvtColor, frame.data, cv2.COLOR_RGB2BGR)
        elif frame.color_format == "GRAY":
            bgr = await asyncio.to_thread(cv2.cvtColor, frame.data, cv2.COLOR_GRAY2BGR)

        if bgr.shape[1] != self._resolution[0] or bgr.shape[0] != self._resolution[1]:
            bgr = await asyncio.to_thread(
                cv2.resize, bgr, self._resolution, interpolation=cv2.INTER_LINEAR
            )

        await asyncio.to_thread(self._writer.write, bgr)
        self._frame_count += 1

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

    @property
    def with_audio(self) -> bool:
        return self._with_audio
