#!/usr/bin/env python3
"""
Utility classes and functions for camera system.
Includes FPS tracking, timing metadata, and configuration loading.
"""

import time
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("CameraUtils")


def load_config_file() -> dict:
    """Load configuration from config.txt file."""
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


class RollingFPS:
    """Calculate FPS using a rolling window."""

    def __init__(self, window_seconds: float = 5.0):
        self.window_seconds = window_seconds
        self.frame_timestamps: deque[float] = deque()

    def add_frame(self, timestamp: Optional[float] = None) -> None:
        if timestamp is None:
            timestamp = time.time()
        self.frame_timestamps.append(timestamp)
        cutoff = timestamp - self.window_seconds
        while self.frame_timestamps and self.frame_timestamps[0] < cutoff:
            self.frame_timestamps.popleft()

    def get_fps(self) -> float:
        if len(self.frame_timestamps) < 2:
            return 0.0
        timespan = self.frame_timestamps[-1] - self.frame_timestamps[0]
        if timespan <= 0:
            return 0.0
        return (len(self.frame_timestamps) - 1) / timespan

    def reset(self) -> None:
        self.frame_timestamps.clear()


@dataclass(slots=True)
class FrameTimingMetadata:
    """Per-frame metadata captured for timing diagnostics."""

    capture_monotonic: Optional[float] = None
    capture_unix: Optional[float] = None
    camera_frame_index: Optional[int] = None
    display_frame_index: Optional[int] = None
    dropped_frames_total: Optional[int] = None
    duplicates_total: Optional[int] = None
    available_camera_fps: Optional[float] = None
    requested_fps: Optional[float] = None
    is_duplicate: bool = False


@dataclass(slots=True)
class _QueuedFrame:
    """Internal queued frame structure for recording."""
    frame: 'np.ndarray'  # type: ignore
    metadata: FrameTimingMetadata
    enqueued_monotonic: float
