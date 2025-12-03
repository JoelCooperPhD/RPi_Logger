"""VOG data logger for CSV file output.

Handles all file I/O for logging VOG trial data to CSV files.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Awaitable

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base.storage_utils import module_filename_prefix

from .protocols import BaseVOGProtocol, VOGDataPacket


class VOGDataLogger:
    """Handles CSV logging for VOG trial data.

    Responsibilities:
    - Directory and file creation
    - CSV header writing
    - Data row formatting and appending
    - Event dispatching for logged data
    """

    def __init__(
        self,
        output_dir: Path,
        port: str,
        protocol: BaseVOGProtocol,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ):
        """Initialize the data logger.

        Args:
            output_dir: Directory for output CSV files
            port: Device port name (used in filename)
            protocol: Protocol instance for CSV formatting
            event_callback: Optional async callback for log events
        """
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

    async def log_trial_data(
        self,
        packet: VOGDataPacket,
        trial_number: int,
        label: Optional[str] = None,
    ) -> Optional[Path]:
        """Log trial data to CSV file.

        Args:
            packet: Parsed data packet from device
            trial_number: Trial number for filename
            label: Optional label (defaults to trial_number as string)

        Returns:
            Path to the data file, or None if logging failed
        """
        try:
            # Ensure output directory exists
            await asyncio.to_thread(self.output_dir.mkdir, parents=True, exist_ok=True)

            # Build filename
            prefix = module_filename_prefix(self.output_dir, "VOG", trial_number, code="VOG")
            port_name = self._sanitize_port_name()
            data_file = self.output_dir / f"{prefix}_{port_name}.csv"

            # Write header if file doesn't exist
            file_exists = await asyncio.to_thread(data_file.exists)
            if not file_exists:
                header = self.protocol.csv_header
                await asyncio.to_thread(self._write_header, data_file, header)
                self.logger.info("Created VOG data file: %s", data_file.name)

            # Prepare row data
            if label is None:
                label = str(trial_number)

            unix_time = int(datetime.now().timestamp())
            ms_since_record = self._calculate_ms_since_record()

            # Format CSV line based on device type
            if self.device_type == 'wvog' and hasattr(self.protocol, 'to_extended_csv_row'):
                line = self.protocol.to_extended_csv_row(packet, label, unix_time, ms_since_record)
            else:
                line = packet.to_csv_row(label, unix_time, ms_since_record)

            # Append to file
            await asyncio.to_thread(self._append_line, data_file, line)
            self.logger.debug(
                "Logged trial: T=%s, Open=%s, Closed=%s",
                trial_number, packet.shutter_open, packet.shutter_closed
            )

            # Dispatch logged event
            await self._dispatch_logged_event(packet, trial_number, label, unix_time, ms_since_record, data_file)

            return data_file

        except Exception as e:
            self.logger.error("Error logging trial data: %s", e, exc_info=True)
            return None

    def _calculate_ms_since_record(self) -> int:
        """Calculate milliseconds since recording started."""
        if self._recording_start_time:
            return int((datetime.now().timestamp() - self._recording_start_time) * 1000)
        return 0

    @staticmethod
    def _write_header(data_file: Path, header: str) -> None:
        """Write CSV header to file (synchronous, run in thread)."""
        with open(data_file, 'w', encoding='utf-8') as f:
            f.write(header + '\n')

    @staticmethod
    def _append_line(data_file: Path, line: str) -> None:
        """Append a line to the CSV file (synchronous, run in thread)."""
        with open(data_file, 'a', encoding='utf-8') as f:
            f.write(line + '\n')

    async def _dispatch_logged_event(
        self,
        packet: VOGDataPacket,
        trial_number: int,
        label: str,
        unix_time: int,
        ms_since_record: int,
        data_file: Path,
    ) -> None:
        """Dispatch trial_logged event via callback."""
        if not self._event_callback:
            return

        payload = {
            'device_id': packet.device_id,
            'device_type': self.device_type,
            'label': label,
            'unix_time': unix_time,
            'ms_since_record': ms_since_record,
            'trial_number': trial_number,
            'shutter_open': packet.shutter_open,
            'shutter_closed': packet.shutter_closed,
            'file_path': str(data_file),
        }

        if self.device_type == 'wvog':
            payload['shutter_total'] = packet.shutter_total
            payload['lens'] = packet.lens
            payload['battery_percent'] = packet.battery_percent

        try:
            await self._event_callback('trial_logged', payload)
        except Exception as e:
            self.logger.error("Error dispatching trial_logged event: %s", e)
