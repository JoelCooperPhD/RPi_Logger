"""Buffered CSV timing logger."""

from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

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
    """Buffered CSV writer with header preservation."""

    def __init__(self, *, trial_number: Optional[int], camera_label: str, flush_every: int = 32) -> None:
        self._trial = trial_number
        self._camera = camera_label
        self._flush_every = max(1, flush_every)
        self._rows: List[List[str]] = []
        self._path: Optional[Path] = None
        self._lock = asyncio.Lock()

    async def start(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists() or not self._path.read_text(encoding="utf-8").strip():
            self._path.write_text(",".join(CSV_HEADER) + "\n", encoding="utf-8")

    def log_frame(self, record: CSVRecord) -> None:
        row = [
            "" if record.trial is None else str(record.trial),
            str(record.frame_number),
            f"{record.write_time_unix:.6f}",
            f"{record.monotonic_time:.9f}",
            "" if record.sensor_timestamp_ns is None else str(record.sensor_timestamp_ns),
            "" if record.hardware_frame_number is None else str(record.hardware_frame_number),
            "" if record.dropped_since_last is None else str(record.dropped_since_last),
            str(record.total_hardware_drops),
            str(record.storage_queue_drops),
        ]
        self._rows.append(row)

    async def flush(self) -> None:
        if not self._path or not self._rows:
            return
        async with self._lock:
            with self._path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(self._rows)
            self._rows.clear()

    async def stop(self) -> None:
        await self.flush()


__all__ = ["CSVLogger", "CSVRecord", "CSV_HEADER"]
