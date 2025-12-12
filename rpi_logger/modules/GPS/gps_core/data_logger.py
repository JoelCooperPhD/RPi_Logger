"""GPS data logger for CSV file output.

Handles all file I/O for logging GPS data to CSV files.
Uses buffered writing with a background thread for performance.
"""

from __future__ import annotations

import csv
import threading
import time
from pathlib import Path
from queue import Queue, Empty
from typing import Any, List, Optional, TextIO

from rpi_logger.core.logging_utils import get_module_logger
from .constants import GPS_CSV_HEADER, MPS_PER_KNOT
from .parsers.nmea_types import GPSFixSnapshot

logger = get_module_logger(__name__)


class GPSDataLogger:
    """Handles CSV logging for GPS data.

    Features:
    - Buffered async writing via background thread
    - Configurable flush threshold
    - Drop detection for overload scenarios

    The logger maintains a write queue and background thread to avoid
    blocking the main processing loop during disk I/O.

    Example:
        data_logger = GPSDataLogger(output_dir, "GPS:serial0")
        data_logger.start_recording(trial_number=1)

        # During GPS processing
        data_logger.log_fix(fix, "GGA", raw_sentence)

        # When done
        data_logger.stop_recording()
    """

    def __init__(
        self,
        output_dir: Path,
        device_id: str,
        flush_threshold: int = 32,
    ):
        """Initialize the data logger.

        Args:
            output_dir: Directory for output CSV files
            device_id: Device identifier for filename (e.g., "GPS:serial0")
            flush_threshold: Number of rows to buffer before flushing to disk
        """
        self.output_dir = output_dir
        self.device_id = device_id
        self._flush_threshold = flush_threshold

        # File handles
        self._record_file: Optional[TextIO] = None
        self._record_writer: Optional[csv.writer] = None
        self._record_path: Optional[Path] = None

        # Buffered writing
        self._write_queue: Queue[Optional[List[Any]]] = Queue(maxsize=1000)
        self._writer_thread: Optional[threading.Thread] = None
        self._dropped_records = 0

        # Recording state
        self._recording = False
        self._trial_number = 1

    @property
    def is_recording(self) -> bool:
        """Check if recording is active."""
        return self._recording

    @property
    def filepath(self) -> Optional[Path]:
        """Return the current CSV file path."""
        return self._record_path

    @property
    def dropped_records(self) -> int:
        """Number of records dropped due to queue overflow."""
        return self._dropped_records

    def _sanitize_device_id(self) -> str:
        """Convert device ID to safe filename component."""
        # GPS:serial0 -> GPS_serial0
        return self.device_id.replace(":", "_").replace("/", "_").replace("\\", "_")

    def start_recording(self, trial_number: int = 1) -> Optional[Path]:
        """Open CSV file and start writer thread.

        Args:
            trial_number: Trial number for the session

        Returns:
            Path to the CSV file, or None if failed
        """
        if self._recording:
            logger.debug("Recording already active for %s", self.device_id)
            return self._record_path

        self._trial_number = trial_number
        self._dropped_records = 0

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename
            device_safe = self._sanitize_device_id()
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{device_safe}_{timestamp}.csv"
            path = self.output_dir / filename

            # Open file and write header
            handle = path.open("w", encoding="utf-8", newline="")
            writer = csv.writer(handle)
            writer.writerow(GPS_CSV_HEADER)

            self._record_file = handle
            self._record_writer = writer
            self._record_path = path

            # Clear queue and start writer thread
            while not self._write_queue.empty():
                try:
                    self._write_queue.get_nowait()
                except Empty:
                    break

            self._writer_thread = threading.Thread(
                target=self._writer_loop,
                name=f"GPSWriter-{device_safe}",
                daemon=True,
            )
            self._writer_thread.start()

            self._recording = True
            logger.info("Started GPS recording: %s", path)
            return path

        except Exception as exc:
            logger.error("Failed to start recording for %s: %s", self.device_id, exc)
            # Ensure file handle is closed on error
            if self._record_file:
                try:
                    self._record_file.close()
                except Exception:
                    pass
            self._record_file = None
            self._record_writer = None
            self._record_path = None
            return None

    def stop_recording(self) -> None:
        """Stop writer thread and close file."""
        if not self._recording:
            return

        # Signal writer thread to stop
        if self._writer_thread and self._writer_thread.is_alive():
            self._write_queue.put(None)  # Sentinel to stop
            self._writer_thread.join(timeout=5.0)
            if self._writer_thread.is_alive():
                logger.warning("Writer thread did not stop in time for %s, retrying", self.device_id)
                self._writer_thread.join(timeout=2.0)
                if self._writer_thread.is_alive():
                    logger.error("Writer thread still alive for %s, proceeding with cleanup", self.device_id)
        self._writer_thread = None

        # Close file handle
        handle = self._record_file
        if handle:
            try:
                handle.close()
            except Exception as exc:
                logger.debug("Error closing recording file: %s", exc)

        if self._dropped_records > 0:
            logger.warning(
                "GPS recording stopped with %d dropped records for %s",
                self._dropped_records,
                self.device_id,
            )

        record_path = self._record_path
        self._record_file = None
        self._record_writer = None
        self._record_path = None
        self._recording = False

        if record_path:
            logger.info("Stopped GPS recording: %s", record_path)

    def log_fix(
        self,
        fix: GPSFixSnapshot,
        sentence_type: str,
        raw_sentence: str,
    ) -> bool:
        """Queue a fix record for writing.

        Args:
            fix: Current GPS fix data
            sentence_type: NMEA sentence type (e.g., "GGA", "RMC")
            raw_sentence: Raw NMEA sentence string

        Returns:
            True if record was queued, False if dropped
        """
        if not self._recording or not self._record_writer:
            return False

        # Calculate speed in m/s
        speed_mps = None
        if fix.speed_knots is not None:
            speed_mps = fix.speed_knots * MPS_PER_KNOT
        elif fix.speed_kmh is not None:
            speed_mps = fix.speed_kmh / 3.6

        # Build row matching GPS_CSV_HEADER order
        row = [
            self._trial_number,
            time.time(),  # recorded_at_unix
            fix.timestamp.isoformat() if fix.timestamp else "",
            fix.latitude,
            fix.longitude,
            fix.altitude_m,
            speed_mps,
            fix.speed_kmh,
            fix.speed_knots,
            fix.speed_mph,
            fix.course_deg,
            fix.fix_quality,
            fix.fix_mode or "",
            1 if fix.fix_valid else 0,
            fix.satellites_in_use,
            fix.satellites_in_view,
            fix.hdop,
            fix.pdop,
            fix.vdop,
            sentence_type,
            raw_sentence,
        ]

        # Queue for async writing
        try:
            self._write_queue.put_nowait(row)
            return True
        except Exception:
            self._dropped_records += 1
            if self._dropped_records % 50 == 1:
                logger.warning(
                    "GPS record queue overflow for %s (dropped: %d)",
                    self.device_id,
                    self._dropped_records,
                )
            return False

    def update_trial_number(self, trial_number: int) -> None:
        """Update the trial number for subsequent records.

        Args:
            trial_number: New trial number
        """
        self._trial_number = trial_number

    def update_output_dir(self, output_dir: Path) -> None:
        """Update the output directory (for session changes).

        Note: This only affects future recordings. If recording is active,
        stop_recording should be called first.

        Args:
            output_dir: New output directory
        """
        self.output_dir = output_dir

    def _writer_loop(self) -> None:
        """Background thread that writes queued records to disk."""
        writer = self._record_writer
        handle = self._record_file
        if not writer or not handle:
            return

        buffer: List[List[Any]] = []
        while True:
            try:
                row = self._write_queue.get(timeout=0.5)
            except Empty:
                # Flush pending buffer on timeout
                if buffer:
                    self._flush_buffer(writer, handle, buffer)
                    buffer.clear()
                continue

            if row is None:
                # Sentinel - flush and exit
                if buffer:
                    self._flush_buffer(writer, handle, buffer)
                break

            buffer.append(row)
            if len(buffer) >= self._flush_threshold:
                self._flush_buffer(writer, handle, buffer)
                buffer.clear()

    def _flush_buffer(
        self,
        writer: csv.writer,
        handle: TextIO,
        buffer: List[List[Any]],
    ) -> None:
        """Write buffered rows to disk."""
        try:
            for row in buffer:
                writer.writerow(row)
            handle.flush()
        except Exception as exc:
            logger.error(
                "Failed to flush %d GPS records to disk: %s",
                len(buffer),
                exc,
            )
