from pathlib import Path
import asyncio
import subprocess
import tempfile
import wave
from typing import Optional, IO

import numpy as np

from ..capture.frame import CapturedFrame, AudioChunk


class AVMuxer:
    def __init__(
        self,
        output_path: Path,
        video_fps: int,
        resolution: tuple[int, int],
        audio_sample_rate: int,
        audio_channels: int,
    ):
        self._output_path = output_path
        self._video_fps = video_fps
        self._resolution = resolution
        self._audio_sample_rate = audio_sample_rate
        self._audio_channels = audio_channels

        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
        self._temp_video_path: Optional[Path] = None
        self._temp_audio_path: Optional[Path] = None

        self._video_process: Optional[asyncio.subprocess.Process] = None
        self._audio_file: Optional[IO[bytes]] = None

        self._running = False
        self._frame_count = 0
        self._audio_samples = 0

    async def start(self) -> None:
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="usbcam_mux_")
        temp_path = Path(self._temp_dir.name)

        self._temp_video_path = temp_path / "video.mp4"
        self._temp_audio_path = temp_path / "audio.wav"

        width, height = self._resolution
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}",
            "-r", str(self._video_fps),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            str(self._temp_video_path),
        ]

        self._video_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        self._audio_file = await asyncio.to_thread(self._open_wav_file)

        self._running = True
        self._frame_count = 0
        self._audio_samples = 0

    def _open_wav_file(self) -> IO[bytes]:
        wf = wave.open(str(self._temp_audio_path), 'wb')
        wf.setnchannels(self._audio_channels)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(self._audio_sample_rate)
        return wf

    async def write_video_frame(self, frame: CapturedFrame) -> None:
        if not self._running or not self._video_process or not self._video_process.stdin:
            return

        data = frame.data
        if frame.color_format == "RGB":
            import cv2
            data = cv2.cvtColor(data, cv2.COLOR_RGB2BGR)

        if data.shape[1] != self._resolution[0] or data.shape[0] != self._resolution[1]:
            import cv2
            data = cv2.resize(data, self._resolution, interpolation=cv2.INTER_LINEAR)

        self._video_process.stdin.write(data.tobytes())
        await self._video_process.stdin.drain()
        self._frame_count += 1

    async def write_audio_chunk(self, chunk: AudioChunk) -> None:
        if not self._running or not self._audio_file:
            return

        audio_float = chunk.data.astype(np.float32)
        audio_int16 = (audio_float * 32767).astype(np.int16)
        await asyncio.to_thread(self._audio_file.writeframes, audio_int16.tobytes())
        self._audio_samples += chunk.samples

    async def stop(self) -> None:
        self._running = False

        if self._video_process:
            if self._video_process.stdin:
                self._video_process.stdin.close()
                await self._video_process.stdin.wait_closed()
            try:
                await asyncio.wait_for(self._video_process.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                self._video_process.kill()
                await self._video_process.wait()
            self._video_process = None

        if self._audio_file:
            await asyncio.to_thread(self._audio_file.close)
            self._audio_file = None

        await self._final_mux()

        if self._temp_dir:
            self._temp_dir.cleanup()
            self._temp_dir = None

    async def _final_mux(self) -> None:
        if not self._temp_video_path or not self._temp_audio_path:
            return

        if not self._temp_video_path.exists():
            return

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(self._temp_video_path),
            "-i", str(self._temp_audio_path),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            str(self._output_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        try:
            await asyncio.wait_for(proc.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def audio_samples(self) -> int:
        return self._audio_samples

    @property
    def output_path(self) -> Path:
        return self._output_path

    @property
    def is_running(self) -> bool:
        return self._running


class SimpleVideoOnlyEncoder:
    def __init__(
        self,
        output_path: Path,
        video_fps: int,
        resolution: tuple[int, int],
    ):
        self._output_path = output_path
        self._video_fps = video_fps
        self._resolution = resolution
        self._process: Optional[asyncio.subprocess.Process] = None
        self._running = False
        self._frame_count = 0

    async def start(self) -> None:
        self._output_path.parent.mkdir(parents=True, exist_ok=True)

        width, height = self._resolution
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}",
            "-r", str(self._video_fps),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            str(self._output_path),
        ]

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._running = True
        self._frame_count = 0

    async def write_frame(self, frame: CapturedFrame) -> None:
        if not self._running or not self._process or not self._process.stdin:
            return

        data = frame.data
        if frame.color_format == "RGB":
            import cv2
            data = cv2.cvtColor(data, cv2.COLOR_RGB2BGR)

        if data.shape[1] != self._resolution[0] or data.shape[0] != self._resolution[1]:
            import cv2
            data = cv2.resize(data, self._resolution, interpolation=cv2.INTER_LINEAR)

        self._process.stdin.write(data.tobytes())
        await self._process.stdin.drain()
        self._frame_count += 1

    async def stop(self) -> None:
        self._running = False
        if self._process:
            if self._process.stdin:
                self._process.stdin.close()
                await self._process.stdin.wait_closed()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            self._process = None

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def is_running(self) -> bool:
        return self._running
