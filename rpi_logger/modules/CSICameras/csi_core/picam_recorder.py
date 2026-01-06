"""Picamera2 native recording with timing-aware output."""
from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any, Optional

try:
    from picamera2.outputs import FfmpegOutput
except ImportError:
    FfmpegOutput = None  # type: ignore


class TimingAwareFfmpegOutput(FfmpegOutput):
    """FfmpegOutput subclass that logs per-frame timing to CSV.

    Preserves the existing CSV format used by the Encoder class for
    compatibility with downstream analysis tools.
    """

    def __init__(
        self,
        output_file: str,
        csv_path: Optional[str] = None,
        trial_number: Optional[int] = None,
        device_id: str = "",
        module_name: str = "CSICameras",
    ) -> None:
        super().__init__(output_file, audio=False)
        self._csv_path = csv_path
        self._csv_file = None
        self._csv_writer = None
        self._trial_number = trial_number
        self._device_id = device_id
        self._module_name = module_name
        self._frame_count = 0
        self._frames_dropped = 0
        self._start_time: Optional[float] = None
        self._start_mono: Optional[float] = None
        self._last_timestamp: Optional[int] = None

    def start(self) -> None:
        super().start()
        self._start_time = time.time()
        self._start_mono = time.perf_counter()
        self._frame_count = 0
        self._frames_dropped = 0

        if self._csv_path:
            self._csv_file = open(self._csv_path, "w", newline="")
            self._csv_writer = csv.writer(self._csv_file)
            self._csv_writer.writerow([
                "trial",
                "module",
                "device_id",
                "label",
                "record_time_unix",
                "record_time_mono",
                "frame_index",
                "sensor_timestamp_ns",
                "video_pts",
            ])

    def outputframe(self, frame: bytes, keyframe: bool = True, timestamp: Optional[int] = None) -> None:
        super().outputframe(frame, keyframe, timestamp)
        self._frame_count += 1
        self._last_timestamp = timestamp

        if self._csv_writer:
            wall_time = time.time()
            mono_time = time.perf_counter()
            self._csv_writer.writerow([
                self._trial_number,
                self._module_name,
                self._device_id,
                "",
                f"{wall_time:.6f}",
                f"{mono_time:.9f}",
                self._frame_count,
                timestamp,
                self._frame_count,
            ])

    def stop(self) -> None:
        super().stop()
        if self._csv_file:
            try:
                self._csv_file.close()
            except Exception:
                pass
            self._csv_file = None
            self._csv_writer = None

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def frames_dropped(self) -> int:
        return self._frames_dropped

    @property
    def duration_sec(self) -> float:
        if self._start_mono is None:
            return 0.0
        return time.perf_counter() - self._start_mono


__all__ = ["TimingAwareFfmpegOutput"]
