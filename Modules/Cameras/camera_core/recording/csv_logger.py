#!/usr/bin/env python3
"""
CSV timing logger for recording frame timing diagnostics.

Runs as an async task to avoid blocking video encoding.
Uses an asyncio queue for efficient async logging.
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import NamedTuple, Optional

from ..camera_utils import FrameTimingMetadata
from ..constants import CSV_FLUSH_INTERVAL_FRAMES, CSV_QUEUE_SIZE, CSV_LOGGER_STOP_TIMEOUT_SECONDS, FRAME_LOG_COUNT

logger = logging.getLogger("CSVLogger")


class CSVLogEntry(NamedTuple):
    """Entry for CSV logging queue"""
    frame_number: int
    write_time_unix: float
    metadata: FrameTimingMetadata


class CSVLogger:
    """
    Async CSV logger for frame timing data.

    Uses an asyncio queue to avoid blocking the video encoding pipeline.
    Batches writes and flushes periodically for efficiency.

    Args:
        camera_id: Camera identifier for logging
        csv_path: Path to CSV output file
        flush_interval: Number of frames between flushes
        queue_size: Maximum queue size
    """

    def __init__(
        self,
        camera_id: int,
        csv_path: Path,
        flush_interval: int = CSV_FLUSH_INTERVAL_FRAMES,
        queue_size: int = CSV_QUEUE_SIZE
    ):
        self.camera_id = camera_id
        self.csv_path = csv_path
        self.flush_interval = flush_interval
        self.queue_size = queue_size

        self._file = None
        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # Drop tracking
        self._accumulated_drops = 0
        self._total_hardware_drops = 0
        self._queue_overflow_drops = 0

    def start(self) -> None:
        """Start CSV logger (synchronous initialization, async background task)"""
        if self._task is not None:
            raise RuntimeError("CSV logger already started")

        try:
            # Open CSV file (synchronous - fast operation)
            self._file = open(self.csv_path, "w", encoding="utf-8", buffering=8192)
            self._file.write(
                "frame_number,write_time_unix,sensor_timestamp_ns,dropped_since_last,total_hardware_drops\n"
            )

            # Create queue and start async task
            self._queue = asyncio.Queue(maxsize=self.queue_size)
            self._running = True
            self._accumulated_drops = 0
            self._total_hardware_drops = 0
            self._queue_overflow_drops = 0

            # Start background task for async logging
            try:
                loop = asyncio.get_running_loop()
                self._task = asyncio.create_task(self._logger_loop())
                logger.debug("Camera %d CSV logger started: %s", self.camera_id, self.csv_path)
            except RuntimeError:
                # No event loop - close file and raise
                self._file.close()
                self._file = None
                raise RuntimeError("No event loop available for CSV logger")
        except Exception:
            # Cleanup file handle on failure
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
            raise

    async def stop(self) -> None:
        """Stop CSV logger task and close file"""
        if self._task is None:
            return

        self._running = False

        # Cancel task if still running
        if not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=CSV_LOGGER_STOP_TIMEOUT_SECONDS)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        self._task = None
        self._queue = None

        # Close file with final sync for durability
        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None

        # Report any queue overflow drops
        if self._queue_overflow_drops > 0:
            logger.warning("Camera %d CSV logger stopped with %d entries lost due to queue overflow",
                         self.camera_id, self._queue_overflow_drops)
        else:
            logger.debug("Camera %d CSV logger stopped", self.camera_id)

    def log_frame(self, frame_number: int, metadata: FrameTimingMetadata) -> None:
        """
        Queue frame timing data for logging (synchronous, non-blocking).

        Args:
            frame_number: Display frame number
            metadata: Frame timing metadata
        """
        if self._queue is None:
            return

        # Track drops (note: this is not thread-safe, but should be called from single thread)
        if metadata.dropped_since_last is not None and metadata.dropped_since_last > 0:
            self._accumulated_drops += metadata.dropped_since_last
            self._total_hardware_drops += metadata.dropped_since_last

        # Queue entry
        entry = CSVLogEntry(
            frame_number=frame_number,
            write_time_unix=time.time(),
            metadata=metadata,
        )

        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            # Drop CSV entry if queue full (preserves video recording)
            self._queue_overflow_drops += 1
            # Log warning periodically (every 10 drops) to avoid log spam
            if self._queue_overflow_drops % 10 == 1:
                logger.warning("Camera %d CSV queue full, dropped %d entries so far (queue size=%d)",
                             self.camera_id, self._queue_overflow_drops, self.queue_size)

    async def _logger_loop(self) -> None:
        """
        CSV logger async loop.
        Processes queue entries and writes to CSV file.
        Uses executor for non-blocking file I/O.
        """
        csv_write_counter = 0
        loop = asyncio.get_event_loop()

        while self._running:
            if self._queue is None:
                break

            try:
                entry = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            # Write entry asynchronously
            await self._write_entry_async(entry, loop)

            # Batch flush with fsync for durability
            csv_write_counter += 1
            if csv_write_counter >= self.flush_interval:
                if self._file is not None:
                    await loop.run_in_executor(None, self._flush_and_sync)
                csv_write_counter = 0

        # Final flush with fsync
        if self._file is not None:
            await loop.run_in_executor(None, self._flush_and_sync)

        logger.debug("Camera %d CSV logger loop exited", self.camera_id)

    def _flush_and_sync(self) -> None:
        """
        Flush file buffer and sync to disk for durability.

        This ensures data survives power loss by writing through OS buffers to disk.
        Called from executor thread to avoid blocking async loop.
        """
        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())

    async def _write_entry_async(self, entry: CSVLogEntry, loop) -> None:
        """
        Write CSV entry to file asynchronously.

        Uses executor to offload blocking I/O to thread pool.

        Args:
            entry: CSV log entry to write
            loop: Event loop for executor
        """
        if self._file is None:
            return

        # Get drop counts (no lock needed - only accessed from this async task)
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

        # Format CSV row - minimal format with only essential data
        row = (
            f"{entry.frame_number},"
            f"{entry.write_time_unix:.6f},"
            f"{entry.metadata.sensor_timestamp_ns if entry.metadata.sensor_timestamp_ns is not None else ''},"
            f"{dropped_since_last if dropped_since_last is not None else ''},"
            f"{total_drops}\n"
        )

        # Write asynchronously using executor (non-blocking)
        await loop.run_in_executor(None, self._file.write, row)
