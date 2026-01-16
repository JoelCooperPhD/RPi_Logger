
import asyncio
import json
from pathlib import Path
from typing import Dict, Any, Optional

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


class SyncMetadataWriter:

    @staticmethod
    async def write_sync_file(
        session_dir: Path,
        trial_number: int,
        session_timestamp: str,
        modules_data: Dict[str, Dict[str, Any]]
    ) -> Optional[Path]:
        """Write unified sync metadata file for trial. Returns path or None on error."""
        if not modules_data:
            logger.warning("No modules data to write to sync file")
            return None

        unix_times = [
            data.get("start_time_unix")
            for data in modules_data.values()
            if "start_time_unix" in data
        ]
        earliest_unix_time = min(unix_times) if unix_times else None

        monotonic_times = [
            data.get("start_time_monotonic")
            for data in modules_data.values()
            if "start_time_monotonic" in data
        ]
        earliest_monotonic_time = min(monotonic_times) if monotonic_times else None

        sync_metadata = {
            "trial_number": trial_number,
            "start_time_unix": earliest_unix_time,
            "start_time_monotonic": earliest_monotonic_time,
            "modules": modules_data
        }

        filename = f"{session_timestamp}_SYNC_trial{trial_number:03d}.json"
        sync_path = session_dir / filename

        def write_json_sync():
            with open(sync_path, 'w', encoding='utf-8') as f:
                json.dump(sync_metadata, f, indent=2)

        try:
            await asyncio.to_thread(write_json_sync)
            logger.info("Wrote sync metadata: %s", filename)
            return sync_path
        except Exception as e:
            logger.warning("Failed to write sync metadata: %s", e)
            return None

    @staticmethod
    async def read_sync_file(sync_path: Path) -> Optional[Dict[str, Any]]:
        """Read sync metadata from file. Returns dict or None on error."""
        def read_json_sync():
            with open(sync_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        try:
            return await asyncio.to_thread(read_json_sync)
        except Exception as e:
            logger.warning("Failed to read sync metadata from %s: %s", sync_path, e)
            return None

    @staticmethod
    def calculate_audio_offset(
        audio_start_unix: float,
        video_start_unix: float
    ) -> float:
        """Calculate audio offset in seconds (positive if audio started after video)."""
        return audio_start_unix - video_start_unix
