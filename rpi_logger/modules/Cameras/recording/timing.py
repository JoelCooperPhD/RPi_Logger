"""Timing metadata writer for video frames."""

import asyncio
import logging
from pathlib import Path
from typing import Optional, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from ..capture import CapturedFrame

logger = logging.getLogger(__name__)


class TimingWriter:
    """CSV timing metadata writer.

    Records timestamp information for each recorded frame to enable
    accurate synchronization with other data streams.

    Format matches Cameras_CSI timing CSV for consistency.
    """

    HEADER = "trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,sensor_timestamp_ns,video_pts\n"
    MODULE = "USBCameras"

    def __init__(self, path: Path, trial: int, device_id: str, label: str = ""):
        """Initialize timing writer.

        Args:
            path: Output CSV file path
            trial: Trial number for this recording
            device_id: Camera device identifier
            label: Optional label for this recording
        """
        self._path = path
        self._trial = trial
        self._device_id = device_id
        self._label = label
        self._file: Optional[TextIO] = None
        self._frame_index = 0

    async def start(self) -> None:
        """Open timing file for writing."""
        self._file = open(self._path, "w")
        self._file.write(self.HEADER)
        self._file.flush()
        self._frame_index = 0
        logger.info("TimingWriter started: %s", self._path)

    async def write_frame(self, frame: "CapturedFrame") -> None:
        """Write timing entry for a frame.

        Args:
            frame: The captured frame
        """
        if self._file:
            self._frame_index += 1
            row = self._format_row(frame, self._frame_index)
            await asyncio.to_thread(self._write_and_flush, row)

    def _write_and_flush(self, row: str) -> None:
        """Write row and flush to disk."""
        self._file.write(row)
        self._file.flush()

    def _format_row(self, frame: "CapturedFrame", frame_index: int) -> str:
        """Format a CSV row matching CSI timing format."""
        return (
            f"{self._trial},{self.MODULE},{self._device_id},{self._label},"
            f"{frame.wall_time:.6f},{frame.timestamp_ns / 1e9:.9f},"
            f"{frame_index},{frame.timestamp_ns},{frame_index}\n"
        )

    async def stop(self) -> None:
        """Close timing file."""
        if self._file:
            self._file.close()
            self._file = None

        logger.info(
            "TimingWriter stopped: %s (%d entries)",
            self._path,
            self._frame_index,
        )

    @property
    def frame_count(self) -> int:
        """Number of timing entries written."""
        return self._frame_index
