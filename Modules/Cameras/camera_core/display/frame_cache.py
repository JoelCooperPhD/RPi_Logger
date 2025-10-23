
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class FrameCache:

    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self.logger = logging.getLogger(f"FrameCache{camera_id}")

        self._latest_frame: Optional[np.ndarray] = None

    def update_frame(self, frame: np.ndarray) -> None:
        self._latest_frame = frame

    def get_display_frame(self) -> Optional[np.ndarray]:
        return self._latest_frame
