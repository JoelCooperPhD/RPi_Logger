"""DRT data logger for CSV file output.

Handles all file I/O for logging DRT trial data to CSV files.
Supports both sDRT and wDRT data formats.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Awaitable
import logging

from rpi_logger.core.logging_utils import get_module_logger
from .protocols import SDRT_CSV_HEADER, WDRT_CSV_HEADER, RT_TIMEOUT_VALUE

logger = get_module_logger(__name__)


class DRTDataLogger:
    """Handles CSV logging for DRT trial data.

    Responsibilities:
    - Directory and file creation
    - CSV header writing
    - Data row formatting and appending
    - Event dispatching for logged data

    Supports both sDRT (7 fields) and wDRT (9 fields) formats.
    """

    def __init__(
        self,
        output_dir: Path,
        device_id: str,
        device_type: str,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ):
        """Initialize the data logger.

        Args:
            output_dir: Directory for output CSV files
            device_id: Device identifier (typically port name)
            device_type: Device type ('sdrt' or 'wdrt')
            event_callback: Optional async callback for log events
        """
        self.output_dir = output_dir
        self.device_id = device_id
        self.device_type = device_type.lower()
        self._event_callback = event_callback

        # CSV file handle caching for reduced I/O overhead
        self._csv_file = None
        self._csv_filepath: Optional[Path] = None
        self._csv_header_written = False

        # Trial label for CSV output
        self._trial_label: str = ""

    @property
    def csv_header(self) -> str:
        """Return the CSV header for this device type."""
        if self.device_type == 'wdrt':
            return WDRT_CSV_HEADER
        return SDRT_CSV_HEADER

    @property
    def filepath(self) -> Optional[Path]:
        """Return the current CSV file path."""
        return self._csv_filepath

    def set_trial_label(self, label: str) -> None:
        """Set the trial label for CSV output."""
        self._trial_label = label

    def _sanitize_port_name(self) -> str:
        """Convert device ID/port path to safe filename component."""
        return self.device_id.lstrip('/').replace('/', '_').replace('\\', '_').lower()

    def _format_device_id_for_csv(self) -> str:
        """Format device ID for CSV output."""
        port_clean = self._sanitize_port_name()
        if self.device_type == 'wdrt':
            return f"wDRT_{port_clean}"
        return f"DRT_{port_clean}"

    def start_recording(self) -> None:
        """Open CSV file for writing trial data (caches handle for session)."""
        if self._csv_file is not None:
            return  # Already open

        if not self.output_dir:
            return

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            device_id_csv = self._format_device_id_for_csv()
            filename = f"{device_id_csv}.csv"
            self._csv_filepath = self.output_dir / filename

            # Check if we need to write header (file doesn't exist or is empty)
            self._csv_header_written = (
                self._csv_filepath.exists() and self._csv_filepath.stat().st_size > 0
            )

            self._csv_file = open(self._csv_filepath, 'a', buffering=1)  # Line buffered
            if not self._csv_header_written:
                self._csv_file.write(self.csv_header + '\n')
                self._csv_header_written = True

            logger.debug("Opened CSV file: %s", self._csv_filepath)
        except Exception as e:
            logger.error("Failed to open CSV file: %s", e)
            self._csv_file = None

    def stop_recording(self) -> None:
        """Close the cached CSV file handle."""
        if self._csv_file is not None:
            try:
                self._csv_file.close()
                logger.debug("Closed CSV file: %s", self._csv_filepath)
            except Exception as e:
                logger.error("Error closing CSV file: %s", e)
            finally:
                self._csv_file = None
                self._csv_filepath = None
        self._trial_label = ""

    def log_trial(self, data: Dict[str, Any], click_count: int = 0) -> bool:
        """Log trial data to CSV file.

        Args:
            data: Trial data dictionary with keys:
                - timestamp: Device timestamp (ms)
                - trial_number: Trial number
                - reaction_time: Reaction time (ms) or -1 for timeout
                - clicks: Number of clicks/responses (optional, uses click_count if not present)
                - battery: Battery percentage (wDRT only)
                - device_utc: Device UTC time (wDRT only)
            click_count: Fallback click count if not in data

        Returns:
            True if logging succeeded
        """
        if not self.output_dir:
            logger.warning("No output directory set, skipping data log")
            return False

        try:
            # Ensure file is open (may have been closed unexpectedly)
            if self._csv_file is None:
                self.start_recording()
            if self._csv_file is None:
                logger.warning("Could not open CSV file, skipping data log")
                return False

            # Common fields
            device_id_csv = self._format_device_id_for_csv()
            unix_time = int(datetime.now().timestamp())
            device_timestamp = data.get('timestamp', 0)
            trial_number = data.get('trial_number', 0)
            clicks = data.get('clicks', click_count)
            reaction_time = data.get('reaction_time', RT_TIMEOUT_VALUE)
            label = self._trial_label if self._trial_label else "NA"

            # Format CSV line based on device type
            if self.device_type == 'wdrt':
                battery = data.get('battery', 0)
                device_utc = data.get('device_utc', 0)
                csv_line = (
                    f"{device_id_csv},{label},{unix_time},{device_timestamp},"
                    f"{trial_number},{clicks},{reaction_time},{battery},{device_utc}\n"
                )
            else:
                # sDRT format: 7 fields
                csv_line = (
                    f"{device_id_csv},{label},{unix_time},{device_timestamp},"
                    f"{trial_number},{clicks},{reaction_time}\n"
                )

            # Write to cached file handle (line-buffered, so flushes automatically)
            self._csv_file.write(csv_line)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Logged trial data to %s (clicks=%d)", self._csv_filepath, clicks)

            return True

        except Exception as e:
            logger.error("Error logging trial data: %s", e)
            return False

    async def dispatch_logged_event(self, trial_number: int) -> None:
        """Dispatch trial_logged event via callback.

        Args:
            trial_number: The trial number that was logged
        """
        if not self._event_callback:
            return

        try:
            await self._event_callback('trial_logged', {
                'filepath': str(self._csv_filepath),
                'trial_number': trial_number,
            })
        except Exception as e:
            logger.error("Error dispatching trial_logged event: %s", e)
