
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from Modules.base import RollingFPS

logger = logging.getLogger(__name__)


def load_config_file() -> dict:
    config_path = Path(__file__).parent.parent / "config.txt"
    config = {}

    if not config_path.exists():
        return config

    try:
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # Strip inline comments (everything after #)
                    if '#' in value:
                        value = value.split('#')[0].strip()
                    config[key] = value
    except Exception as e:
        logger.warning("Failed to load config file: %s", e)

    return config




@dataclass(slots=True)
class FrameTimingMetadata:
    sensor_timestamp_ns: Optional[int] = None  # Hardware timestamp (nanoseconds since boot) - ESSENTIAL
    dropped_since_last: Optional[int] = None  # Dropped frames detected via timestamp analysis - ESSENTIAL
    display_frame_index: Optional[int] = None  # Frame number for CSV/video overlay - ESSENTIAL

    camera_frame_index: Optional[int] = None  # Hardware frame number (same as display_frame_index now)
    software_frame_index: Optional[int] = None  # Software counter (for diagnostics)


@dataclass(slots=True)
class _QueuedFrame:
    frame: 'np.ndarray'  # type: ignore
    metadata: FrameTimingMetadata
    enqueued_monotonic: float
