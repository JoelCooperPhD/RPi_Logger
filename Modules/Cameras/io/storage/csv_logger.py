"""Asynchronous CSV logger for the Cameras runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .constants import (
    CSV_FLUSH_INTERVAL_FRAMES,
    CSV_LOGGER_STOP_TIMEOUT_SECONDS,
    CSV_QUEUE_SIZE,
    FRAME_LOG_COUNT,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CSVLogEntry:
    camera_id: int
    frame_number: int
    write_time_unix: float
    sensor_timestamp_ns: Optional[int]
    dropped_since_last: Optional[int]
    total_hardware_drops: int
    storage_queue_drops: int


class CameraCSVLogger:
    """Queue-based CSV writer mirroring the production camera module."""

    def __init__(
        self,
        camera_id: int,
        csv_path: Path,
        trial_number: int = 1,
        *,
        camera_name: Optional[str] = None,
        flush_interval: int = CSV_FLUSH_INTERVAL_FRAMES,
        queue_size: int = CSV_QUEUE_SIZE,
    ) -> None:
        self.camera_id = camera_id
        self.csv_path = csv_path
        self.trial_number = trial_number
        self.flush_interval = flush_interval
        self.queue_size = queue_size
        resolved_name = (camera_name or f"Camera {camera_id}").strip() or f"Camera {camera_id}"
        self.camera_name = resolved_name

        self._file: Optional[object] = None
        self._queue: Optional[asyncio.Queue[CSVLogEntry]] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

        self._total_hardware_drops = 0
        self._queue_overflow_drops = 0

    @property
    def total_hardware_drops(self) -> int:
        return self._total_hardware_drops

    async def start(self) -> None:
        if self._task is not None:
            return

        file_exists = self.csv_path.exists()
        self._file = open(self.csv_path, "a" if file_exists else "w", encoding="utf-8", buffering=8192)
        if not file_exists:
            self._file.write(
                "trial,frame_number,write_time_unix,sensor_timestamp_ns,dropped_since_last,total_hardware_drops,storage_queue_drops\n"
            )

        self._queue = asyncio.Queue(maxsize=self.queue_size)
        self._running = True
        self._queue_overflow_drops = 0
        self._total_hardware_drops = 0

        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._logger_loop(), name=f"CSVLoggerCam{self.camera_id}")
        logger.info("%s CSV logger started -> %s", self.camera_name, self.csv_path)

    async def stop(self) -> None:
        if self._task is None:
            return

        self._running = False
        task = self._task
        self._task = None

        queue = self._queue
        if queue is not None:
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            try:
                await asyncio.wait_for(queue.join(), timeout=CSV_LOGGER_STOP_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("%s CSV queue did not drain before timeout", self.camera_name)
            self._queue = None

        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=CSV_LOGGER_STOP_TIMEOUT_SECONDS)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None

        if self._queue_overflow_drops > 0:
            logger.warning(
                "%s CSV logger dropped %d entries due to queue overflow",
                self.camera_name,
                self._queue_overflow_drops,
            )
        else:
            logger.info("%s CSV logger stopped", self.camera_name)

    def log_frame(
        self,
        frame_number: int,
        *,
        frame_time_unix: Optional[float] = None,
        sensor_timestamp_ns: Optional[int],
        dropped_since_last: Optional[int],
        storage_queue_drops: int = 0,
    ) -> None:
        if self._queue is None:
            return

        if dropped_since_last is not None and dropped_since_last > 0:
            self._total_hardware_drops += dropped_since_last

        if frame_time_unix is None:
            frame_time_unix = time.time()

        entry = CSVLogEntry(
            camera_id=self.camera_id,
            frame_number=frame_number,
            write_time_unix=frame_time_unix,
            sensor_timestamp_ns=sensor_timestamp_ns,
            dropped_since_last=dropped_since_last,
            total_hardware_drops=self._total_hardware_drops,
            storage_queue_drops=storage_queue_drops,
        )

        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            self._queue_overflow_drops += 1
            if self._queue_overflow_drops % 10 == 1:
                logger.warning(
                    "%s CSV logger queue full (size=%d), dropped %d entries",
                    self.camera_name,
                    self.queue_size,
                    self._queue_overflow_drops,
                )

    async def _logger_loop(self) -> None:
        assert self._queue is not None
        queue = self._queue
        csv_write_counter = 0
        loop = asyncio.get_running_loop()

        while True:
            if not self._running and queue.empty():
                break
            try:
                entry = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if entry is None:
                queue.task_done()
                break

            await loop.run_in_executor(None, self._write_entry, entry)
            queue.task_done()

            csv_write_counter += 1
            if csv_write_counter >= self.flush_interval:
                await loop.run_in_executor(None, self._flush_and_sync)
                csv_write_counter = 0

        # Final flush
        await loop.run_in_executor(None, self._flush_and_sync)
        logger.debug("%s CSV logger loop exited", self.camera_name)

    def _write_entry(self, entry: CSVLogEntry) -> None:
        if self._file is None:
            return

        if entry.frame_number < FRAME_LOG_COUNT:
            logger.info(
                "%s frame %d -> dropped=%s total_drops=%s sensor_ts=%s",
                self.camera_name,
                entry.frame_number,
                entry.dropped_since_last,
                entry.total_hardware_drops,
                entry.sensor_timestamp_ns,
            )

        row = (
            f"{self.trial_number},"
            f"{entry.frame_number},"
            f"{entry.write_time_unix:.6f},"
            f"{entry.sensor_timestamp_ns if entry.sensor_timestamp_ns is not None else ''},"
            f"{entry.dropped_since_last if entry.dropped_since_last is not None else ''},"
            f"{entry.total_hardware_drops},"
            f"{entry.storage_queue_drops}\n"
        )
        self._file.write(row)

    def _flush_and_sync(self) -> None:
        if self._file is None:
            return
        self._file.flush()
        os.fsync(self._file.fileno())


__all__ = ['CameraCSVLogger']
