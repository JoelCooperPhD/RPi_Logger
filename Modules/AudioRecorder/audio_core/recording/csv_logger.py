
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import NamedTuple, Optional

from Modules.base import AsyncTaskManager
from ..constants import CSV_FLUSH_INTERVAL_CHUNKS, CSV_QUEUE_SIZE, CSV_LOGGER_STOP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class CSVLogEntry(NamedTuple):
    chunk_number: int
    write_time_unix: float
    frames_in_chunk: int


class AudioCSVLogger:

    def __init__(
        self,
        device_id: int,
        csv_path: Path,
        trial_number: int = 1,
        flush_interval: int = CSV_FLUSH_INTERVAL_CHUNKS,
        queue_size: int = CSV_QUEUE_SIZE
    ):
        self.device_id = device_id
        self.csv_path = csv_path
        self.trial_number = trial_number
        self.flush_interval = flush_interval
        self.queue_size = queue_size

        self._file = None
        self._queue: Optional[asyncio.Queue] = None
        self._running = False
        self._tasks = AsyncTaskManager(f"AudioCSVLogger{device_id}", logger)

        self._total_frames = 0
        self._queue_overflow_drops = 0

    def start(self) -> None:
        if self._running:
            raise RuntimeError("Audio CSV logger already started")

        try:
            file_exists = self.csv_path.exists()
            mode = "a" if file_exists else "w"
            self._file = open(self.csv_path, mode, encoding="utf-8", buffering=8192)

            if not file_exists:
                self._file.write(
                    "trial,chunk_number,write_time_unix,frames_in_chunk,total_frames\n"
                )

            self._queue = asyncio.Queue(maxsize=self.queue_size)
            self._running = True
            self._total_frames = 0
            self._queue_overflow_drops = 0

            try:
                loop = asyncio.get_running_loop()
                self._tasks.create(self._logger_loop(), name=f"csv_logger_{self.device_id}")
                logger.debug("Audio device %d CSV logger started: %s", self.device_id, self.csv_path)
            except RuntimeError:
                self._file.close()
                self._file = None
                raise RuntimeError("No event loop available for CSV logger")
        except Exception:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
            raise

    async def stop(self) -> None:
        self._running = False
        await self._tasks.shutdown(timeout=CSV_LOGGER_STOP_TIMEOUT_SECONDS)
        self._queue = None

        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None

        if self._queue_overflow_drops > 0:
            logger.warning("Audio device %d CSV logger stopped with %d entries lost due to queue overflow",
                         self.device_id, self._queue_overflow_drops)
        else:
            logger.debug("Audio device %d CSV logger stopped", self.device_id)

    def log_chunk(self, chunk_number: int, frames_in_chunk: int) -> None:
        if self._queue is None:
            return

        self._total_frames += frames_in_chunk

        entry = CSVLogEntry(
            chunk_number=chunk_number,
            write_time_unix=time.time(),
            frames_in_chunk=frames_in_chunk,
        )

        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            self._queue_overflow_drops += 1
            if self._queue_overflow_drops % 10 == 1:
                logger.warning("Audio device %d CSV queue full, dropped %d entries so far (queue size=%d)",
                             self.device_id, self._queue_overflow_drops, self.queue_size)

    async def _logger_loop(self) -> None:
        csv_write_counter = 0
        loop = asyncio.get_event_loop()

        while self._running:
            if self._queue is None:
                break

            try:
                entry = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            await self._write_entry_async(entry, loop)

            csv_write_counter += 1
            if csv_write_counter >= self.flush_interval:
                if self._file is not None:
                    await loop.run_in_executor(None, self._flush_and_sync)
                csv_write_counter = 0

        if self._file is not None:
            await loop.run_in_executor(None, self._flush_and_sync)

        logger.debug("Audio device %d CSV logger loop exited", self.device_id)

    def _flush_and_sync(self) -> None:
        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())

    async def _write_entry_async(self, entry: CSVLogEntry, loop) -> None:
        if self._file is None:
            return

        row = (
            f"{self.trial_number},"
            f"{entry.chunk_number},"
            f"{entry.write_time_unix:.6f},"
            f"{entry.frames_in_chunk},"
            f"{self._total_frames}\n"
        )

        await loop.run_in_executor(None, self._file.write, row)
