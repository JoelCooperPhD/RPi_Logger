
import time
from collections import deque
from typing import Optional


class RollingFPS:

    def __init__(self, window_seconds: float = 5.0, max_fps: float = 1000.0):
        self.window_seconds = window_seconds
        # Bound the deque to prevent unbounded growth under high load
        # maxlen = window_seconds * max_fps provides headroom for high frame rates
        max_frames = int(window_seconds * max_fps)
        self.frame_timestamps = deque(maxlen=max_frames)
        self._last_fps = 0.0

    def add_frame(self, timestamp: Optional[float] = None) -> None:
        if timestamp is None:
            timestamp = time.time()

        self.frame_timestamps.append(timestamp)

        cutoff_time = timestamp - self.window_seconds
        while self.frame_timestamps and self.frame_timestamps[0] < cutoff_time:
            self.frame_timestamps.popleft()

    def get_fps(self) -> float:
        if len(self.frame_timestamps) < 2:
            return 0.0

        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        while self.frame_timestamps and self.frame_timestamps[0] < cutoff_time:
            self.frame_timestamps.popleft()

        if len(self.frame_timestamps) < 2:
            return 0.0

        time_span = self.frame_timestamps[-1] - self.frame_timestamps[0]

        if time_span <= 0:
            return 0.0

        fps = (len(self.frame_timestamps) - 1) / time_span
        self._last_fps = fps
        return fps

    def reset(self) -> None:
        self.frame_timestamps.clear()
        self._last_fps = 0.0

    @property
    def frame_count(self) -> int:
        return len(self.frame_timestamps)

    @property
    def window_duration(self) -> float:
        if len(self.frame_timestamps) < 2:
            return 0.0
        return self.frame_timestamps[-1] - self.frame_timestamps[0]
