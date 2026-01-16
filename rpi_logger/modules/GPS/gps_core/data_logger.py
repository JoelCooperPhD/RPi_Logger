"""GPS CSV logger with buffered async writing via background thread."""

from __future__ import annotations

import csv
import threading
import time
from pathlib import Path
from queue import Queue, Empty
from typing import Any, List, Optional, TextIO

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base.storage_utils import derive_session_token, sanitize_device_id
from .constants import GPS_CSV_HEADER, MPS_PER_KNOT
from .parsers.nmea_types import GPSFixSnapshot

logger = get_module_logger(__name__)


class GPSDataLogger:
    """CSV logger with buffered async writing and drop detection."""

    def __init__(
        self,
        output_dir: Path,
        device_id: str,
        flush_threshold: int = 32,
    ):
        """Initialize logger with output dir, device ID, and flush threshold."""
        self.output_dir = output_dir
        self.device_id = device_id
        self._flush_threshold = flush_threshold
        self._record_file: Optional[TextIO] = None
        self._record_writer: Optional[csv.writer] = None
        self._record_path: Optional[Path] = None
        self._write_queue: Queue[Optional[List[Any]]] = Queue(maxsize=1000)
        self._writer_thread: Optional[threading.Thread] = None
        self._dropped_records = 0
        self._recording = False
        self._trial_number = 1
        self._trial_label: str = ""

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

    def _build_session_filepath(self) -> Optional[Path]:
        if not self.output_dir:
            return None

        token = derive_session_token(self.output_dir, "GPS")
        device_safe = sanitize_device_id(self.device_id)
        # Avoid redundant prefix (e.g., "GPS_GPS_...") when device ID already
        # starts with the module code
        if device_safe.startswith("gps_"):
            filename = f"{token}_{device_safe}.csv"
        else:
            filename = f"{token}_GPS_{device_safe}.csv"
        return self.output_dir / filename

    def start_recording(self, trial_number: int = 1, trial_label: str = "") -> Optional[Path]:
        """Open CSV file and start writer thread. Returns path or None if failed."""
        if self._recording:
            logger.debug("Recording already active for %s", self.device_id)
            return self._record_path

        try:
            trial_number = int(trial_number)
        except (TypeError, ValueError):
            trial_number = 1
        if trial_number <= 0:
            trial_number = 1
        self._trial_number = trial_number
        self._trial_label = trial_label
        self._dropped_records = 0

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            device_safe = sanitize_device_id(self.device_id)
            path = self._build_session_filepath()
            if path is None:
                return None
            needs_header = not path.exists() or path.stat().st_size == 0

            handle = path.open("a", encoding="utf-8", newline="")
            writer = csv.writer(handle)
            if needs_header:
                writer.writerow(GPS_CSV_HEADER)

            self._record_file = handle
            self._record_writer = writer
            self._record_path = path

            while not self._write_queue.empty():
                try:
                    self._write_queue.get_nowait()
                except Empty:
                    break

            self._writer_thread = threading.Thread(
                target=self._writer_loop, name=f"GPSWriter-{device_safe}", daemon=True
            )
            self._writer_thread.start()

            self._recording = True
            logger.info("Started GPS recording: %s", path)
            return path

        except Exception as exc:
            logger.error("Failed to start recording for %s: %s", self.device_id, exc)
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

        if self._writer_thread and self._writer_thread.is_alive():
            self._write_queue.put(None)
            self._writer_thread.join(timeout=5.0)
            if self._writer_thread.is_alive():
                logger.warning("Writer thread did not stop in time for %s, retrying", self.device_id)
                self._writer_thread.join(timeout=2.0)
                if self._writer_thread.is_alive():
                    logger.warning("Writer thread still alive for %s, proceeding with cleanup", self.device_id)
        self._writer_thread = None

        if self._record_file:
            try:
                self._record_file.close()
            except Exception as exc:
                logger.debug("Error closing recording file: %s", exc)

        if self._dropped_records > 0:
            logger.warning("GPS recording stopped with %d dropped records for %s", self._dropped_records, self.device_id)

        record_path = self._record_path
        self._record_file = None
        self._record_writer = None
        self._record_path = None
        self._recording = False

        if record_path:
            logger.info("Stopped GPS recording: %s", record_path)

    def log_fix(self, fix: GPSFixSnapshot, sentence_type: str, raw_sentence: str) -> bool:
        """Queue fix record for writing. Returns True if queued, False if dropped."""
        if not self._recording or not self._record_writer:
            return False

        speed_mps = None
        if fix.speed_knots is not None:
            speed_mps = fix.speed_knots * MPS_PER_KNOT
        elif fix.speed_kmh is not None:
            speed_mps = fix.speed_kmh / 3.6

        record_time_unix = time.time()
        record_time_mono = time.perf_counter()

        device_time_unix = ""
        if fix.timestamp is not None:
            try:
                device_time_unix = fix.timestamp.timestamp()
            except Exception:
                device_time_unix = ""

        row = [
            self._trial_number, "GPS", self.device_id, self._trial_label,
            f"{record_time_unix:.6f}", f"{record_time_mono:.9f}",
            fix.timestamp.isoformat() if fix.timestamp else "", device_time_unix,
            fix.latitude, fix.longitude, fix.altitude_m, speed_mps,
            fix.speed_kmh, fix.speed_knots, fix.speed_mph, fix.course_deg,
            fix.fix_quality, fix.fix_mode or "", 1 if fix.fix_valid else 0,
            fix.satellites_in_use, fix.satellites_in_view,
            fix.hdop, fix.pdop, fix.vdop, sentence_type, raw_sentence,
        ]

        try:
            self._write_queue.put_nowait(row)
            return True
        except Exception:
            self._dropped_records += 1
            if self._dropped_records % 50 == 1:
                logger.warning("GPS record queue overflow for %s (dropped: %d)", self.device_id, self._dropped_records)
            return False

    def update_trial_number(self, trial_number: int) -> None:
        """Update trial number for subsequent records."""
        self._trial_number = trial_number

    def update_output_dir(self, output_dir: Path) -> None:
        """Update output directory (only affects future recordings)."""
        self.output_dir = output_dir

    def _writer_loop(self) -> None:
        """Background thread writing queued records to disk."""
        writer = self._record_writer
        handle = self._record_file
        if not writer or not handle:
            return

        buffer: List[List[Any]] = []
        while True:
            try:
                row = self._write_queue.get(timeout=0.5)
            except Empty:
                if buffer:
                    self._flush_buffer(writer, handle, buffer)
                    buffer.clear()
                continue

            if row is None:
                if buffer:
                    self._flush_buffer(writer, handle, buffer)
                break

            buffer.append(row)
            if len(buffer) >= self._flush_threshold:
                self._flush_buffer(writer, handle, buffer)
                buffer.clear()

    def _flush_buffer(self, writer: csv.writer, handle: TextIO, buffer: List[List[Any]]) -> None:
        """Write buffered rows to disk."""
        try:
            for row in buffer:
                writer.writerow(row)
            handle.flush()
        except Exception as exc:
            logger.error("Failed to flush %d GPS records to disk: %s", len(buffer), exc)
