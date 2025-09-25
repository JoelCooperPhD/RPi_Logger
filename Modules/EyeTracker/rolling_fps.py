#!/usr/bin/env python3
"""
Rolling FPS Calculator
Tracks frame delivery rates using a circular buffer for rolling window calculations.
"""

import time
from collections import deque
from typing import Optional


class RollingFPS:
    """Calculate FPS using a rolling window with circular buffer"""

    def __init__(self, window_seconds: float = 5.0):
        """
        Initialize rolling FPS calculator

        Args:
            window_seconds: Time window in seconds for rolling average
        """
        self.window_seconds = window_seconds
        self.frame_timestamps = deque()
        self._last_fps = 0.0

    def add_frame(self, timestamp: Optional[float] = None) -> None:
        """
        Add a frame timestamp to the rolling buffer

        Args:
            timestamp: Frame timestamp, uses current time if None
        """
        if timestamp is None:
            timestamp = time.time()

        self.frame_timestamps.append(timestamp)

        # Remove old timestamps outside the window
        cutoff_time = timestamp - self.window_seconds
        while self.frame_timestamps and self.frame_timestamps[0] < cutoff_time:
            self.frame_timestamps.popleft()

    def get_fps(self) -> float:
        """
        Get current FPS based on frames in the rolling window

        Returns:
            FPS as frames per second
        """
        if len(self.frame_timestamps) < 2:
            return 0.0

        # Calculate FPS based on frames in the current window
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        # Clean up old timestamps first
        while self.frame_timestamps and self.frame_timestamps[0] < cutoff_time:
            self.frame_timestamps.popleft()

        if len(self.frame_timestamps) < 2:
            return 0.0

        # Calculate actual time span of frames in buffer
        time_span = self.frame_timestamps[-1] - self.frame_timestamps[0]

        if time_span <= 0:
            return 0.0

        # FPS = (frames - 1) / time_span
        # We use frames-1 because N frames span N-1 intervals
        fps = (len(self.frame_timestamps) - 1) / time_span
        self._last_fps = fps
        return fps

    def reset(self) -> None:
        """Reset the rolling buffer"""
        self.frame_timestamps.clear()
        self._last_fps = 0.0

    @property
    def frame_count(self) -> int:
        """Get current number of frames in the rolling window"""
        return len(self.frame_timestamps)

    @property
    def window_duration(self) -> float:
        """Get actual duration of frames currently in buffer"""
        if len(self.frame_timestamps) < 2:
            return 0.0
        return self.frame_timestamps[-1] - self.frame_timestamps[0]