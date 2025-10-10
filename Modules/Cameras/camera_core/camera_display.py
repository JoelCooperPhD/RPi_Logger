#!/usr/bin/env python3
"""
CAMERA DISPLAY - Display handling only.

This module handles ONLY display operations:
- Storing latest display frame (thread-safe)
- Providing frames to main thread for OpenCV display

The actual cv2.imshow() happens in camera_system.py preview loop.
This just provides the frames.
"""

import logging
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger("CameraDisplay")


class CameraDisplay:
    """
    Display frame manager.

    Thread-safe storage for latest display frame.
    Main thread can call get_display_frame() to retrieve for cv2.imshow().
    """

    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self.logger = logging.getLogger(f"CameraDisplay{camera_id}")

        # Thread-safe frame storage
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None

    def update_frame(self, frame: np.ndarray) -> None:
        """
        Update the display frame (called from processor).

        Thread-safe - can be called from any thread.
        """
        with self._frame_lock:
            self._latest_frame = frame

    def get_display_frame(self) -> Optional[np.ndarray]:
        """
        Get latest display frame (called from main thread).

        Thread-safe - returns copy of latest frame.
        """
        with self._frame_lock:
            return self._latest_frame
