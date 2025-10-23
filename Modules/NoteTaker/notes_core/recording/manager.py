
import asyncio
import csv
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import aiofiles

from ..constants import CSV_HEADERS, CSV_FILENAME

logger = logging.getLogger(__name__)


class RecordingManager:

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.csv_file_path: Optional[Path] = None
        self.recording = False
        self.session_start_time: Optional[datetime] = None
        self.note_count = 0

    async def start_recording(self) -> bool:
        if self.recording:
            logger.warning("Recording already active")
            return False

        try:
            await asyncio.to_thread(self.session_dir.mkdir, parents=True, exist_ok=True)

            self.csv_file_path = self.session_dir / CSV_FILENAME
            self.session_start_time = datetime.now()
            self.note_count = 0

            # Use aiofiles for async file I/O
            async with aiofiles.open(self.csv_file_path, 'w', newline='') as f:
                # Write CSV header using in-memory buffer then flush to file
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=CSV_HEADERS)
                writer.writeheader()
                await f.write(buffer.getvalue())

            self.recording = True
            logger.info("Started note recording: %s", self.csv_file_path)
            return True

        except Exception as e:
            logger.error("Failed to start recording: %s", e, exc_info=True)
            return False

    def stop_recording(self) -> bool:
        if not self.recording:
            logger.warning("Recording not active")
            return False

        try:
            self.recording = False
            logger.info("Stopped note recording: %d notes recorded to %s",
                       self.note_count, self.csv_file_path)
            return True

        except Exception as e:
            logger.error("Failed to stop recording: %s", e, exc_info=True)
            return False

    async def add_note(self, note_text: str, recording_modules: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        if not self.recording:
            logger.warning("Cannot add note - recording not active")
            return None

        if not note_text.strip():
            logger.warning("Cannot add empty note")
            return None

        try:
            now = datetime.now()
            elapsed_seconds = (now - self.session_start_time).total_seconds()
            elapsed_str = self._format_elapsed_time(elapsed_seconds)

            modules_str = ", ".join(recording_modules) if recording_modules else ""

            note_record = {
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],  # Millisecond precision
                "session_elapsed_time": elapsed_str,
                "note_text": note_text.strip(),
                "recording_modules": modules_str
            }

            # Use aiofiles for async file append
            async with aiofiles.open(self.csv_file_path, 'a', newline='') as f:
                # Write CSV row using in-memory buffer then flush to file
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=CSV_HEADERS)
                writer.writerow(note_record)
                await f.write(buffer.getvalue())

            self.note_count += 1
            logger.info("Added note #%d (elapsed: %s): '%s'",
                       self.note_count, elapsed_str, note_text[:50])

            return note_record

        except Exception as e:
            logger.error("Failed to add note: %s", e, exc_info=True)
            return None

    async def get_all_notes(self) -> List[Dict[str, Any]]:
        if not self.csv_file_path:
            return []

        # Use asyncio.to_thread for path.exists() check
        if not await asyncio.to_thread(self.csv_file_path.exists):
            return []

        try:
            # Use aiofiles for async file read
            async with aiofiles.open(self.csv_file_path, 'r', newline='') as f:
                content = await f.read()
                # Parse CSV in memory
                reader = csv.DictReader(io.StringIO(content))
                return list(reader)
        except Exception as e:
            logger.error("Failed to read notes: %s", e, exc_info=True)
            return []

    def get_session_elapsed_time(self) -> str:
        if not self.session_start_time:
            return "00:00:00"

        elapsed_seconds = (datetime.now() - self.session_start_time).total_seconds()
        return self._format_elapsed_time(elapsed_seconds)

    @staticmethod
    def _format_elapsed_time(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
