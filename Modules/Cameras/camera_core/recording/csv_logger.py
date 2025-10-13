#!/usr/bin/env python3
"""
CSV timing logger for recording frame timing diagnostics.

Runs in a separate thread to avoid blocking video encoding.
Uses a queue for efficient async logging.
"""

import logging
import queue
import threading
import time
from pathlib import Path
from typing import NamedTuple, Optional

from ..camera_utils import FrameTimingMetadata

logger = logging.getLogger("CSVLogger")


class CSVLogEntry(NamedTuple):
    """Entry for CSV logging queue"""
    frame_number: int
    write_time_unix: float
    metadata: FrameTimingMetadata


class CSVLogger:
    """
    Separate-thread CSV logger for frame timing data.

    Uses a queue to avoid blocking the video encoding pipeline.
    Batches writes and flushes periodically for efficiency.

    Args:
        camera_id: Camera identifier for logging
        csv_path: Path to CSV output file
        flush_interval: Number of frames between flushes
        queue_size: Maximum queue size
    """

    def __init__(self, camera_id: int, csv_path: Path, flush_interval: int = 60, queue_size: int = 300):
        self.camera_id = camera_id
        self.csv_path = csv_path
        self.flush_interval = flush_interval
        self.queue_size = queue_size

        self._file = None
        self._queue: Optional[queue.Queue] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._queue_sentinel = object()

        # Drop tracking
        self._accumulated_drops = 0
        self._total_hardware_drops = 0
        self._drops_lock = threading.Lock()

    def start(self) -> None:
        """Start CSV logger thread"""
        if self._thread is not None:
            raise RuntimeError("CSV logger already started")

        # Open CSV file
        self._file = open(self.csv_path, "w", encoding="utf-8", buffering=8192)
        self._file.write(
            "frame_number,write_time_unix,sensor_timestamp_ns,dropped_since_last,total_hardware_drops\n"
        )

        # Create queue and thread
        self._queue = queue.Queue(maxsize=self.queue_size)
        self._stop_event.clear()
        self._accumulated_drops = 0
        self._total_hardware_drops = 0

        self._thread = threading.Thread(
            target=self._logger_loop,
            name=f"Cam{self.camera_id}-csv",
            daemon=True
        )
        self._thread.start()
        logger.debug("Camera %d CSV logger started: %s", self.camera_id, self.csv_path)

    def stop(self) -> None:
        """Stop CSV logger thread and close file"""
        if self._thread is None:
            return

        self._stop_event.set()

        # Send sentinel to unblock queue
        if self._queue is not None:
            try:
                self._queue.put_nowait(self._queue_sentinel)
            except queue.Full:
                pass

        # Wait for thread to finish
        if self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._thread = None
        self._queue = None

        # Close file
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None

        logger.debug("Camera %d CSV logger stopped", self.camera_id)

    def log_frame(self, frame_number: int, metadata: FrameTimingMetadata) -> None:
        """
        Queue frame timing data for logging.

        Args:
            frame_number: Display frame number
            metadata: Frame timing metadata
        """
        if self._queue is None:
            return

        # Track drops
        with self._drops_lock:
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
        except queue.Full:
            # Drop CSV entry if queue full (preserves video recording)
            pass

    def _logger_loop(self) -> None:
        """
        CSV logger thread main loop.
        Processes queue entries and writes to CSV file.
        """
        csv_write_counter = 0

        while not self._stop_event.is_set():
            if self._queue is None:
                break

            try:
                entry = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if entry is self._queue_sentinel:
                break

            # Write entry
            self._write_entry(entry)

            # Batch flush
            csv_write_counter += 1
            if csv_write_counter >= self.flush_interval:
                if self._file is not None:
                    self._file.flush()
                csv_write_counter = 0

        # Final flush
        if self._file is not None:
            self._file.flush()

        logger.debug("Camera %d CSV logger loop exited", self.camera_id)

    def _write_entry(self, entry: CSVLogEntry) -> None:
        """
        Write CSV entry to file.

        Args:
            entry: CSV log entry to write
        """
        if self._file is None:
            return

        # Get accumulated drops with lock
        with self._drops_lock:
            dropped_since_last = entry.metadata.dropped_since_last
            total_drops = self._total_hardware_drops

            # If we have accumulated drops, use that (handles skipped frames)
            if self._accumulated_drops > 0:
                dropped_since_last = self._accumulated_drops
                self._accumulated_drops = 0

        # Debug: Log first few frames and any drops
        if entry.frame_number <= 5 or (dropped_since_last is not None and dropped_since_last > 0):
            logger.info("Frame %d: hardware_frame_number=%s, software_frame_index=%s, dropped=%s, total=%s",
                       entry.frame_number,
                       entry.metadata.camera_frame_index,
                       entry.metadata.software_frame_index,
                       dropped_since_last,
                       total_drops)

        # Format and write CSV row - minimal format with only essential data
        row = (
            f"{entry.frame_number},"
            f"{entry.write_time_unix:.6f},"
            f"{entry.metadata.sensor_timestamp_ns if entry.metadata.sensor_timestamp_ns is not None else ''},"
            f"{dropped_since_last if dropped_since_last is not None else ''},"
            f"{total_drops}\n"
        )

        self._file.write(row)
