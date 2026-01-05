"""Preview frame processing - YUV420 to BGR conversion."""
from __future__ import annotations

import cv2
import numpy as np

from rpi_logger.modules.CSICameras.csi_core.backends.picam_color import get_picam_color_format


def yuv420_to_bgr(frame: np.ndarray) -> np.ndarray:
    """Convert YUV420 to BGR, accounting for IMX296 color bug.

    Bug active (bgr): YUV chroma swapped, COLOR_YUV2BGR_I420 correct.
    Bug fixed (rgb): Normal YUV, convert RGB->BGR.
    """
    if get_picam_color_format() == "bgr":
        # Bug active: YUV has swapped chroma, BGR conversion is correct
        return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
    else:
        # Bug fixed: Normal YUV, convert to RGB then BGR
        rgb = cv2.cvtColor(frame, cv2.COLOR_YUV2RGB_I420)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


__all__ = ["yuv420_to_bgr"]
