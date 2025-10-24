
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import aiofiles

from Modules.base.io_utils import get_versioned_filename
from ..constants import HEADERS

logger = logging.getLogger(__name__)


class RecordingManager:

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir

        filename = get_versioned_filename(session_dir, datetime.now())
        self.txt_file_path = self.session_dir / filename
        self.recording = False
        self.session_start_time: Optional[datetime] = None
        self.note_count = 0

    async def start_recording(self) -> bool:
        if self.recording:
            logger.warning("Recording already active")
            return False

        try:
            await asyncio.to_thread(self.session_dir.mkdir, parents=True, exist_ok=True)

            file_exists = await asyncio.to_thread(self.txt_file_path.exists)

            if not file_exists:
                async with aiofiles.open(self.txt_file_path, 'w') as f:
                    await f.write(HEADERS + "\n")
                logger.info("Created new note file: %s", self.txt_file_path)
            else:
                async with aiofiles.open(self.txt_file_path, 'r') as f:
                    lines = await f.readlines()
                    self.note_count = len(lines) - 1
                logger.info("Appending to existing note file: %s (current notes: %d)", self.txt_file_path, self.note_count)

            self.session_start_time = datetime.now()
            self.recording = True
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
                       self.note_count, self.txt_file_path)
            return True

        except Exception as e:
            logger.error("Failed to stop recording: %s", e, exc_info=True)
            return False

    async def pause_recording(self):
        raise NotImplementedError("Pause not supported by note recording")

    async def resume_recording(self):
        raise NotImplementedError("Resume not supported by note recording")

    async def add_note(self, note_text: str, recording_modules: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        if not self.recording:
            logger.warning("Cannot add note - recording not active")
            return None

        if not note_text.strip():
            logger.warning("Cannot add empty note")
            return None

        try:
            timestamp = time.time()
            note_content = note_text.strip()

            row = f"Note,{note_content},{timestamp}\n"

            async with aiofiles.open(self.txt_file_path, 'a') as f:
                await f.write(row)

            self.note_count += 1
            logger.info("Added note #%d: '%s'", self.note_count, note_text[:50])

            note_record = {
                "note_text": note_content,
                "timestamp": timestamp
            }

            return note_record

        except Exception as e:
            logger.error("Failed to add note: %s", e, exc_info=True)
            return None

    async def get_all_notes(self) -> List[Dict[str, Any]]:
        if not self.txt_file_path:
            return []

        if not await asyncio.to_thread(self.txt_file_path.exists):
            return []

        try:
            async with aiofiles.open(self.txt_file_path, 'r') as f:
                content = await f.read()
                lines = content.strip().split('\n')

            notes = []
            for line in lines[1:]:
                if not line.strip():
                    continue

                parts = line.split(',', 2)
                if len(parts) >= 3:
                    notes.append({
                        "note_text": parts[1],
                        "timestamp": float(parts[2])
                    })
            return notes
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
