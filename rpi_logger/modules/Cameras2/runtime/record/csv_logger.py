"""Async CSV logger for per-frame timing (Cameras2)."""

from __future__ import annotations

import asyncio
import contextlib
import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger

CSV_HEADER = [
    "trial",
    "frame_number",
    "write_time_unix",
    "monotonic_time",
    "sensor_timestamp_ns",
    "hardware_frame_number",
    "dropped_since_last",
    "total_hardware_drops",
    "storage_queue_drops",
]


@dataclass(slots=True)
class CSVRecord:
    """Single timing log entry."""

    trial: Optional[int]
    frame_number: int
    write_time_unix: float
    monotonic_time: float
    sensor_timestamp_ns: Optional[int]
    hardware_frame_number: Optional[int]
    dropped_since_last: Optional[int]
    total_hardware_drops: int
    storage_queue_drops: int


class CSVLogger:
    """Queue-based CSV writer mirroring the Cameras module timing CSV."""

    def __init__(
        self,
        *,
        trial_number: Optional[int] = None,
        camera_label: str | None = None,
        queue_size: int = 200,
        flush_every: int = 32,
        logger: LoggerLike = None,
    ) -> None:
        self.trial_number = trial_number
        self.camera_label = camera_label or "Camera"
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._queue_size = queue_size
        self._flush_every = max(1, flush_every)
        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._file = None
        self._writer = None
        self._queue_overflow_drops = 0
        self._writes_since_flush = 0
        self._sentinel = object()

    async def start(self, csv_path: Path) -> None:
        """Open file/queue and spawn logger loop."""
        await asyncio.to_thread(csv_path.parent.mkdir, parents=True, exist_ok=True)
        file_exists = csv_path.exists()
        file_size = csv_path.stat().st_size if file_exists else 0
        self._queue_overflow_drops = 0
        self._writes_since_flush = 0

        self._queue = asyncio.Queue(maxsize=self._queue_size)
        self._file = await asyncio.to_thread(
            open, csv_path, "a" if file_exists else "w", newline="", encoding="utf-8"
        )
        self._writer = csv.writer(self._file)
        if file_size == 0:
            await asyncio.to_thread(self._writer.writerow, CSV_HEADER)

        self._task = asyncio.create_task(self._loop(), name=f"CSVLogger:{csv_path.name}")
        self._logger.info("%s timing CSV -> %s", self.camera_label, csv_path)

    async def stop(self) -> None:
        if not self._queue or not self._task:
            await self._close_file()
            return
        await self._queue.put(self._sentinel)
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        await self._close_file()
        self._queue = None
        self._task = None
        if self._queue_overflow_drops:
            self._logger.warning(
                "%s timing CSV dropped %d entries due to queue overflow",
                self.camera_label,
                self._queue_overflow_drops,
            )

    def log_frame(self, record: CSVRecord) -> None:
        """Non-blocking enqueue of a timing record."""
        if not self._queue:
            return
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self._queue_overflow_drops += 1
            if self._queue_overflow_drops % 10 == 1:
                self._logger.warning(
                    "%s timing CSV queue full (size=%d), dropped=%d",
                    self.camera_label,
                    self._queue_size,
                    self._queue_overflow_drops,
                )

    @property
    def queue_overflow_drops(self) -> int:
        return self._queue_overflow_drops

    async def _loop(self) -> None:
        assert self._queue and self._writer and self._file
        try:
            while True:
                record = await self._queue.get()
                if record is self._sentinel:
                    self._queue.task_done()
                    break
                await asyncio.to_thread(self._writer.writerow, self._format_row(record))
                self._writes_since_flush += 1
                if self._writes_since_flush >= self._flush_every:
                    await self._flush()
                self._queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            await self._flush(final=True)

    async def _flush(self, *, final: bool = False) -> None:
        if not self._file:
            return
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self._file.flush)
            if final:
                await asyncio.to_thread(os.fsync, self._file.fileno())
        self._writes_since_flush = 0

    async def _close_file(self) -> None:
        if not self._file:
            return
        await self._flush(final=True)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self._file.close)
        self._file = None
        self._writer = None

    @staticmethod
    def _format_row(record: CSVRecord) -> list:
        return [
            record.trial if record.trial is not None else "",
            record.frame_number,
            f"{record.write_time_unix:.6f}",
            f"{record.monotonic_time:.9f}",
            record.sensor_timestamp_ns if record.sensor_timestamp_ns is not None else "",
            record.hardware_frame_number if record.hardware_frame_number is not None else "",
            record.dropped_since_last if record.dropped_since_last is not None else "",
            record.total_hardware_drops,
            record.storage_queue_drops,
        ]
