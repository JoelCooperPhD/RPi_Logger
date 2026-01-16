"""VOG data logger for CSV file output."""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Awaitable

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base.storage_utils import derive_session_token

from .protocols import BaseVOGProtocol, VOGDataPacket


class VOGDataLogger:
    """CSV logging for VOG trial data (directory/file creation, headers, rows, events)."""

    def __init__(self, output_dir: Path, port: str, protocol: BaseVOGProtocol,
                 event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None):
        """Initialize logger with output directory, port, protocol, and optional event callback."""
        self.output_dir = output_dir
        self.port = port
        self.protocol = protocol
        self._event_callback = event_callback
        self._recording_start_time: Optional[float] = None
        self.logger = get_module_logger(f"VOGDataLogger[{protocol.device_type}]")

    @property
    def device_type(self) -> str:
        """Return device type from protocol."""
        return self.protocol.device_type

    def start_recording(self) -> None:
        """Mark the start of a recording session."""
        self._recording_start_time = datetime.now().timestamp()

    def stop_recording(self) -> None:
        """Mark the end of a recording session."""
        self._recording_start_time = None

    @property
    def is_recording(self) -> bool:
        """Return True if recording is active."""
        return self._recording_start_time is not None

    def _sanitize_port_name(self) -> str:
        """Convert port path to safe filename component."""
        return self.port.lstrip('/').replace('/', '_').replace('\\', '_').lower()

    def _resolve_data_file(self) -> Path:
        token = derive_session_token(self.output_dir, "VOG")
        port_name = self._sanitize_port_name()
        return self.output_dir / f"{token}_VOG_{port_name}.csv"

    async def log_trial_data(self, packet: VOGDataPacket, trial_number: int,
                            label: Optional[str] = None) -> Optional[Path]:
        """Log trial data to CSV. Returns path to data file or None if failed."""
        try:
            data_file = self._resolve_data_file()
            label = label if label is not None else ""
            record_time_unix = time.time()
            record_time_mono = time.perf_counter()

            line = self.protocol.format_csv_row(packet, label, record_time_unix, record_time_mono)
            header = self.protocol.csv_header

            created_new = await asyncio.to_thread(
                self._batch_write, self.output_dir, data_file, header, line)
            if created_new:
                self.logger.info("Created VOG data file: %s", data_file.name)

            await self._dispatch_logged_event(packet, trial_number, label,
                                             record_time_unix, record_time_mono, data_file)
            return data_file
        except Exception as e:
            self.logger.warning("Error logging trial data: %s", e, exc_info=True)
            return None

    def _calculate_ms_since_record(self) -> int:
        """Calculate milliseconds since recording started."""
        if self._recording_start_time:
            return int((datetime.now().timestamp() - self._recording_start_time) * 1000)
        return 0

    @staticmethod
    def _batch_write(output_dir: Path, data_file: Path, header: str, line: str) -> bool:
        """Batch file I/O (run in thread). Returns True if new file created."""
        output_dir.mkdir(parents=True, exist_ok=True)
        created_new = not data_file.exists()
        with open(data_file, 'w' if created_new else 'a', encoding='utf-8') as f:
            if created_new:
                f.write(header + '\n')
            f.write(line + '\n')
        return created_new

    async def _dispatch_logged_event(self, packet: VOGDataPacket, trial_number: int,
                                     label: str, record_time_unix: float,
                                     record_time_mono: float, data_file: Path) -> None:
        """Dispatch trial_logged event via callback."""
        if not self._event_callback:
            return
        payload = {
            'device_id': packet.device_id, 'device_type': self.device_type,
            'label': label, 'record_time_unix': record_time_unix,
            'record_time_mono': record_time_mono, 'trial_number': trial_number,
            'shutter_open': packet.shutter_open, 'shutter_closed': packet.shutter_closed,
            'file_path': str(data_file)}
        payload.update(self.protocol.get_extended_packet_data(packet))
        try:
            await self._event_callback('trial_logged', payload)
        except Exception as e:
            self.logger.warning("Error dispatching trial_logged event: %s", e)
