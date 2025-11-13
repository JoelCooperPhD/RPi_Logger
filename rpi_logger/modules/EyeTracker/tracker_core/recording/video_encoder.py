import asyncio
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np


class VideoEncoder:
    """Minimal video encoder wrapper supporting FFmpeg or OpenCV backends."""

    def __init__(self, resolution: Tuple[int, int], fps: float, *, use_ffmpeg: bool = True) -> None:
        self.resolution = resolution
        self.fps = fps
        self.use_ffmpeg = use_ffmpeg

        self._process: Optional[asyncio.subprocess.Process] = None
        self._writer: Optional[cv2.VideoWriter] = None

    async def start(self, output_path: Path) -> None:
        width, height = self.resolution

        if self.use_ffmpeg:
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "rawvideo",
                "-vcodec",
                "rawvideo",
                "-s",
                f"{width}x{height}",
                "-pix_fmt",
                "bgr24",
                "-r",
                str(self.fps),
                "-i",
                "-",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "23",
                str(output_path),
            ]

            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        else:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(output_path), fourcc, self.fps, (width, height))
            if not writer.isOpened():
                raise RuntimeError("Failed to start OpenCV video writer")
            self._writer = writer

    def write_frame(self, frame: np.ndarray) -> None:
        width, height = self.resolution
        if frame.shape[:2] != (height, width):
            frame = cv2.resize(frame, (width, height))

        frame_data = np.ascontiguousarray(frame)

        if self.use_ffmpeg:
            if not self._process or self._process.returncode is not None:
                return
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(frame_data.tobytes())
                self._process.stdin.flush()
            except Exception:  # pragma: no cover - defensive
                pass
        else:
            if self._writer is not None:
                self._writer.write(frame_data)

    async def stop(self) -> None:
        if self.use_ffmpeg:
            if self._process is None:
                return
            try:
                assert self._process.stdin is not None
                self._process.stdin.close()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:  # pragma: no cover - defensive
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2)
            except Exception:  # pragma: no cover - defensive
                self._process.terminate()
            finally:
                self._process = None
        else:
            if self._writer is not None:
                self._writer.release()
                self._writer = None

    async def cleanup(self) -> None:
        await self.stop()

    def is_running(self) -> bool:
        if self.use_ffmpeg:
            return self._process is not None and self._process.returncode is None
        return self._writer is not None
