from pathlib import Path
import asyncio
from typing import TextIO

from ..capture.frame import CapturedFrame, AudioChunk


class TimingCSVWriter:
    HEADER = "trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,capture_timestamp_ns,video_pts,audio_pts\n"
    MODULE = "USBCameras"

    def __init__(self, path: Path, trial_number: int, device_id: str, label: str = ""):
        self._path = path
        self._trial = trial_number
        self._device_id = device_id
        self._label = label
        self._file: TextIO | None = None
        self._frame_index = 0
        self._audio_pts = 0

    async def start(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = await asyncio.to_thread(self._open_file)
        self._frame_index = 0
        self._audio_pts = 0

    def _open_file(self) -> TextIO:
        f = open(self._path, 'w', newline='')
        f.write(self.HEADER)
        f.flush()
        return f

    async def write_frame(self, frame: CapturedFrame, audio_pts: int = 0) -> None:
        if not self._file:
            return
        self._frame_index += 1
        self._audio_pts = audio_pts
        row = self._format_row(frame, self._frame_index, audio_pts)
        await asyncio.to_thread(self._write_and_flush, row)

    def _write_and_flush(self, row: str) -> None:
        if self._file:
            self._file.write(row)
            self._file.flush()

    def _format_row(self, frame: CapturedFrame, frame_index: int, audio_pts: int) -> str:
        return (
            f"{self._trial},{self.MODULE},{self._device_id},{self._label},"
            f"{frame.wall_time:.6f},{frame.monotonic_ns / 1e9:.9f},"
            f"{frame_index},{frame.capture_timestamp_ns},{frame_index},{audio_pts}\n"
        )

    async def stop(self) -> None:
        if self._file:
            await asyncio.to_thread(self._file.close)
            self._file = None

    @property
    def frame_count(self) -> int:
        return self._frame_index

    @property
    def path(self) -> Path:
        return self._path
