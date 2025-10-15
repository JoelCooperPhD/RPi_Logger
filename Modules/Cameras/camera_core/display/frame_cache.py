#!/usr/bin/env python3
"""
FRAME CACHE - Display frame caching only.

This module handles ONLY frame caching for display:
- Storing latest display frame (lock-free, atomic)
- Providing frames to main thread for display

The actual display rendering happens in GUI/mode code.
This just provides the frames.
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("FrameCache")


class FrameCache:
    """
    Display frame cache with lock-free atomic design.

    Lock-free storage for latest display frame using atomic reference assignment.
    Main thread can call get_display_frame() to retrieve for display.

    Design Rationale:
    - Single reference assignment is atomic in CPython (GIL guarantees atomicity)
    - No lock needed for simple reference swapping
    - Eliminates lock contention at 30-60 FPS update rates
    - Safe for concurrent access from async and sync contexts
    - Reader may get frame N or N+1, but never a corrupted frame

    Performance Benefits:
    - Zero overhead for updates (no lock acquisition)
    - No blocking in async processor loop
    - No potential for priority inversion or deadlock
    """

    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self.logger = logging.getLogger(f"FrameCache{camera_id}")

        # Lock-free frame storage
        # Atomic reference assignment (safe in CPython due to GIL)
        self._latest_frame: Optional[np.ndarray] = None

    def update_frame(self, frame: np.ndarray) -> None:
        """
        Update the display frame (called from processor).

        Lock-free atomic update - no synchronization needed.
        Safe for concurrent access due to CPython's atomic reference assignment.
        """
        self._latest_frame = frame

    def get_display_frame(self) -> Optional[np.ndarray]:
        """
        Get latest display frame (called from main thread).

        Lock-free atomic read - returns current frame reference.
        May return frame N or N+1 if update happens during read, but never corrupted.
        """
        return self._latest_frame
