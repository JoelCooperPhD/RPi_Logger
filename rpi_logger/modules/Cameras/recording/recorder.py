"""Video recorder using OpenCV VideoWriter."""

import asyncio
import cv2
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..capture import CapturedFrame

logger = logging.getLogger(__name__)


class VideoRecorder:
    """Simple OpenCV video writer for video-only output.

    For video+audio output, use AVMuxer instead.
    """

    def __init__(self, path: Path, resolution: tuple[int, int], fps: int):
        """Initialize video recorder.

        Args:
            path: Output file path (.avi recommended)
            resolution: Video resolution (width, height)
            fps: Frame rate for video container
        """
        self._path = path
        self._resolution = resolution
        self._fps = fps
        self._writer: Optional[cv2.VideoWriter] = None
        self._frame_count = 0

    async def start(self) -> None:
        """Open video file for writing."""
        fourcc = cv2.VideoWriter.fourcc(*"MJPG")
        self._writer = cv2.VideoWriter(
            str(self._path), fourcc, self._fps, self._resolution
        )

        if not self._writer.isOpened():
            raise RuntimeError(f"Failed to open video writer: {self._path}")

        self._frame_count = 0
        logger.info(
            "VideoRecorder started: %s (%dx%d @ %d fps)",
            self._path,
            *self._resolution,
            self._fps,
        )

    async def write_frame(self, frame: "CapturedFrame") -> None:
        """Write a frame to video file.

        Args:
            frame: Captured frame to write
        """
        if self._writer:
            # Run in thread to avoid blocking event loop
            await asyncio.to_thread(self._writer.write, frame.data)
            self._frame_count += 1

    async def stop(self) -> None:
        """Close video file."""
        if self._writer:
            self._writer.release()
            self._writer = None

        logger.info(
            "VideoRecorder stopped: %s (%d frames)",
            self._path,
            self._frame_count,
        )

    @property
    def frame_count(self) -> int:
        """Number of frames written."""
        return self._frame_count
