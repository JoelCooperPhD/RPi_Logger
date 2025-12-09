import asyncio
import os
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
        self._output_path: Optional[Path] = None
        self._flush_interval = 600  # frames (2 minutes at 5fps)
        self._frames_since_flush = 0

    async def start(self, output_path: Path) -> None:
        width, height = self.resolution
        self._output_path = output_path
        self._frames_since_flush = 0

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

    @staticmethod
    def _resize_and_encode(frame: np.ndarray, resolution: Tuple[int, int]) -> bytes:
        width, height = resolution
        if frame.shape[:2] != (height, width):
            frame = cv2.resize(frame, (width, height))
        return np.ascontiguousarray(frame).tobytes()

    @staticmethod
    def _resize_only(frame: np.ndarray, resolution: Tuple[int, int]) -> np.ndarray:
        width, height = resolution
        if frame.shape[:2] != (height, width):
            frame = cv2.resize(frame, (width, height))
        return np.ascontiguousarray(frame)

    async def write_frame(self, frame: np.ndarray) -> None:
        if self.use_ffmpeg:
            # Offload resize and byte conversion to thread
            frame_bytes = await asyncio.to_thread(self._resize_and_encode, frame, self.resolution)

            if not self._process or self._process.returncode is not None:
                return
            assert self._process.stdin is not None
            self._process.stdin.write(frame_bytes)
            await self._process.stdin.drain()
        else:
            # Offload resize to thread
            processed_frame = await asyncio.to_thread(self._resize_only, frame, self.resolution)

            if self._writer is not None:
                self._writer.write(processed_frame)

        # Periodic fsync for crash safety
        self._frames_since_flush += 1
        if self._frames_since_flush >= self._flush_interval:
            self._frames_since_flush = 0
            await self._fsync()

    async def _fsync(self) -> None:
        """Sync file to disk for crash safety."""
        if self._output_path is None:
            return
        try:
            # For FFmpeg subprocess, we can't directly fsync the pipe
            # but we can fsync the output file periodically
            fd = os.open(str(self._output_path), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except (OSError, FileNotFoundError):
            pass  # File may not exist yet or be locked

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
