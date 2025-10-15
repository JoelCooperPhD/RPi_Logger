#!/usr/bin/env python3
"""
Utility classes and functions for camera system.
Includes FPS tracking, timing metadata, and configuration loading.
"""

import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from Modules.base import RollingFPS

logger = logging.getLogger("CameraUtils")


def load_config_file() -> dict:
    """
    Load configuration from config.txt file.

    NOTE: This is a legacy function kept for backward compatibility.
    For new code, use: from camera_core.config import load_config_file

    Returns:
        Simple dict with string values (no type conversion)
    """
    # Config is in the parent directory (Cameras/), not in camera_core/
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


# Note: RollingFPS is now imported from Modules.base.utils
# (removed duplicate implementation)


@dataclass(slots=True)
class FrameTimingMetadata:
    """
    Per-frame metadata for timing analysis and CSV logging.

    Only essential fields needed for the minimal 5-column CSV format.
    """
    sensor_timestamp_ns: Optional[int] = None  # Hardware timestamp (nanoseconds since boot) - ESSENTIAL
    dropped_since_last: Optional[int] = None  # Dropped frames detected via timestamp analysis - ESSENTIAL
    display_frame_index: Optional[int] = None  # Frame number for CSV/video overlay - ESSENTIAL

    # Diagnostic fields (for logging only, not written to CSV)
    camera_frame_index: Optional[int] = None  # Hardware frame number (same as display_frame_index now)
    software_frame_index: Optional[int] = None  # Software counter (for diagnostics)


@dataclass(slots=True)
class _QueuedFrame:
    """Internal queued frame structure for recording."""
    frame: 'np.ndarray'  # type: ignore
    metadata: FrameTimingMetadata
    enqueued_monotonic: float
