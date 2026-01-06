"""Preview frame processing - YUV420 to BGR conversion."""
from __future__ import annotations

from typing import Optional

import numpy as np

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    _HAS_CV2 = False

from rpi_logger.modules.CSICameras.csi_core.backends.picam_color import get_picam_color_format


def yuv420_to_bgr(frame: np.ndarray) -> Optional[np.ndarray]:
    """Convert YUV420 to BGR, accounting for IMX296 color bug.

    Bug active (bgr): YUV chroma swapped, COLOR_YUV2BGR_I420 correct.
    Bug fixed (rgb): Normal YUV, convert RGB->BGR.

    Returns None if cv2 is not available.
    """
    if not _HAS_CV2:
        return None

    if get_picam_color_format() == "bgr":
        return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
    else:
        rgb = cv2.cvtColor(frame, cv2.COLOR_YUV2RGB_I420)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


__all__ = ["yuv420_to_bgr"]
