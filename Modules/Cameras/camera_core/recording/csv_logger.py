
import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

from Modules.base.io_utils import get_versioned_filename
from ..camera_utils import FrameTimingMetadata
from ..constants import CSV_FLUSH_INTERVAL_FRAMES, CSV_QUEUE_SIZE, CSV_LOGGER_STOP_TIMEOUT_SECONDS, FRAME_LOG_COUNT

logger = logging.getLogger(__name__)


class CSVLogEntry(NamedTuple):
    frame_number: int
    write_time_unix: float
    metadata: FrameTimingMetadata


class CSVLogger:

    def __init__(
        self,
        camera_id: int,
        csv_path: Path,
        trial_number: int = 1,
        flush_interval: int = CSV_FLUSH_INTERVAL_FRAMES,
        queue_size: int = CSV_QUEUE_SIZE
    ):
        self.camera_id = camera_id
        self.csv_path = csv_path
        self.trial_number = trial_number
        self.flush_interval = flush_interval
        self.queue_size = queue_size

        self._file = None
        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

        self._accumulated_drops = 0
        self._total_hardware_drops = 0
        self._queue_overflow_drops = 0

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("CSV logger already started")

        try:
            file_exists = self.csv_path.exists()
            mode = "a" if file_exists else "w"
            self._file = open(self.csv_path, mode, encoding="utf-8", buffering=8192)

            if not file_exists:
                self._file.write(
                    "trial,frame_number,write_time_unix,sensor_timestamp_ns,dropped_since_last,total_hardware_drops\n"
                )

            self._queue = asyncio.Queue(maxsize=self.queue_size)
            self._running = True
            self._accumulated_drops = 0
            self._total_hardware_drops = 0
            self._queue_overflow_drops = 0

            try:
                loop = asyncio.get_running_loop()
                self._task = asyncio.create_task(self._logger_loop())
                logger.debug("Camera %d CSV logger started: %s", self.camera_id, self.csv_path)
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
        if self._task is None:
            return

        self._running = False

        if not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=CSV_LOGGER_STOP_TIMEOUT_SECONDS)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        self._task = None
        self._queue = None

        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None

        if self._queue_overflow_drops > 0:
            logger.warning("Camera %d CSV logger stopped with %d entries lost due to queue overflow",
                         self.camera_id, self._queue_overflow_drops)
        else:
            logger.debug("Camera %d CSV logger stopped", self.camera_id)

    def log_frame(self, frame_number: int, metadata: FrameTimingMetadata) -> None:
        if self._queue is None:
            return

        if metadata.dropped_since_last is not None and metadata.dropped_since_last > 0:
            self._accumulated_drops += metadata.dropped_since_last
            self._total_hardware_drops += metadata.dropped_since_last

        entry = CSVLogEntry(
            frame_number=frame_number,
            write_time_unix=time.time(),
            metadata=metadata,
        )

        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            self._queue_overflow_drops += 1
            # Log warning periodically (every 10 drops) to avoid log spam
            if self._queue_overflow_drops % 10 == 1:
                logger.warning("Camera %d CSV queue full, dropped %d entries so far (queue size=%d)",
                             self.camera_id, self._queue_overflow_drops, self.queue_size)

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

        logger.debug("Camera %d CSV logger loop exited", self.camera_id)

    def _flush_and_sync(self) -> None:
        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())

    async def _write_entry_async(self, entry: CSVLogEntry, loop) -> None:
        if self._file is None:
            return

        dropped_since_last = entry.metadata.dropped_since_last
        total_drops = self._total_hardware_drops

        # Debug: Log first few frames and any drops
        if entry.frame_number <= FRAME_LOG_COUNT or (dropped_since_last is not None and dropped_since_last > 0):
            logger.info("Frame %d: hardware_frame_number=%s, software_frame_index=%s, dropped=%s, total=%s",
                       entry.frame_number,
                       entry.metadata.camera_frame_index,
                       entry.metadata.software_frame_index,
                       dropped_since_last,
                       total_drops)

        row = (
            f"{self.trial_number},"
            f"{entry.frame_number},"
            f"{entry.write_time_unix:.6f},"
            f"{entry.metadata.sensor_timestamp_ns if entry.metadata.sensor_timestamp_ns is not None else ''},"
            f"{dropped_since_last if dropped_since_last is not None else ''},"
            f"{total_drops}\n"
        )

        await loop.run_in_executor(None, self._file.write, row)
