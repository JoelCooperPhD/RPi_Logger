
import asyncio
import json
import logging
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
        """
        Write unified synchronization metadata file for a trial.

        Args:
            session_dir: Session directory path
            trial_number: Trial number
            session_timestamp: Session timestamp string (from dirname)
            modules_data: Dict mapping module name to metadata dict

        Returns:
            Path to created sync file, or None on error

        Example modules_data:
        {
            "AudioRecorder_0": {
                "device_id": 0,
                "device_name": "USB Audio",
                "sample_rate": 48000,
                "chunk_size": 1024,
                "start_time_unix": 1729789123.456789,
                "start_time_monotonic": 12345.678,
                "audio_file": "path/to/audio.wav",
                "timing_csv": "path/to/audio_timing.csv"
            },
            "Camera_0": {
                "camera_id": 0,
                "fps": 30.0,
                "resolution": [1920, 1080],
                "start_time_unix": 1729789123.457,
                "start_time_monotonic": 12345.679,
                "video_file": "path/to/video.mp4",
                "timing_csv": "path/to/camera_timing.csv"
            }
        }
        """
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
            logger.error("Failed to write sync metadata: %s", e)
            return None

    @staticmethod
    async def read_sync_file(sync_path: Path) -> Optional[Dict[str, Any]]:
        """
        Read synchronization metadata from file.

        Args:
            sync_path: Path to sync JSON file

        Returns:
            Sync metadata dict, or None on error
        """
        def read_json_sync():
            with open(sync_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        try:
            return await asyncio.to_thread(read_json_sync)
        except Exception as e:
            logger.error("Failed to read sync metadata from %s: %s", sync_path, e)
            return None

    @staticmethod
    def calculate_audio_offset(
        audio_start_unix: float,
        video_start_unix: float
    ) -> float:
        """
        Calculate audio offset relative to video for muxing.

        Args:
            audio_start_unix: Audio recording start time (Unix timestamp)
            video_start_unix: Video recording start time (Unix timestamp)

        Returns:
            Offset in seconds (positive if audio started after video)
        """
        return audio_start_unix - video_start_unix
