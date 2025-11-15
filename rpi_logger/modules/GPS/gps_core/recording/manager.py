import asyncio
import csv
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..gps_handler import GPSHandler

logger = logging.getLogger(__name__)


class GPSRecordingManager:

    def __init__(self, gps_handler: 'GPSHandler'):
        self.gps_handler = gps_handler
        self.recording = False
        self.current_trial = 0
        self.csv_file: Optional[Path] = None
        self.csv_writer = None
        self.file_handle = None
        self.record_task: Optional[asyncio.Task] = None

    def set_gps_handler(self, gps_handler: 'GPSHandler') -> None:
        """Swap the GPS data source without restarting the recorder."""
        self.gps_handler = gps_handler
        logger.debug("Recording manager GPS handler updated")

    async def start_recording(self, session_dir: Path, trial_number: int) -> bool:
        if self.recording:
            logger.warning("Already recording")
            return False

        self.current_trial = trial_number
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.csv_file = session_dir / f"{timestamp}_GPS_trial{trial_number:03d}.csv"
        session_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.file_handle = open(self.csv_file, 'w', newline='')
            self.csv_writer = csv.writer(self.file_handle)

            self.csv_writer.writerow([
                'timestamp',
                'latitude',
                'longitude',
                'altitude',
                'speed_kmh',
                'heading',
                'satellites',
                'fix_quality',
                'hdop'
            ])
            self.file_handle.flush()

            self.recording = True
            self.record_task = asyncio.create_task(self._record_loop())

            logger.info("Started GPS recording: %s", self.csv_file)
            return True

        except Exception as e:
            logger.error("Failed to start recording: %s", e, exc_info=True)
            if self.file_handle:
                self.file_handle.close()
            return False

    async def stop_recording(self) -> bool:
        if not self.recording:
            logger.warning("Not recording")
            return False

        self.recording = False

        if self.record_task:
            self.record_task.cancel()
            try:
                await self.record_task
            except asyncio.CancelledError:
                pass

        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None

        logger.info("Stopped GPS recording: %s", self.csv_file)
        return True

    async def _record_loop(self) -> None:
        logger.info("GPS recording loop started")

        try:
            while self.recording:
                data = self.gps_handler.get_latest_data()

                if data['fix_quality'] > 0:
                    self.csv_writer.writerow([
                        datetime.now().isoformat(),
                        f"{data['latitude']:.8f}",
                        f"{data['longitude']:.8f}",
                        f"{data['altitude']:.2f}",
                        f"{data['speed_kmh']:.2f}",
                        f"{data['heading']:.2f}",
                        data['satellites'],
                        data['fix_quality'],
                        f"{data['hdop']:.2f}"
                    ])
                    self.file_handle.flush()

                await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.debug("Recording loop cancelled")
        except Exception as e:
            logger.error("Recording loop error: %s", e, exc_info=True)
        finally:
            logger.info("GPS recording loop stopped")

    async def cleanup(self) -> None:
        if self.recording:
            await self.stop_recording()
