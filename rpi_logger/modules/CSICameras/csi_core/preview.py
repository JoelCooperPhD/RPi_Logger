"""
Preview frame processing for CSI cameras.

Handles preview frame conversion from YUV420 lores stream to BGR.
"""
from __future__ import annotations

import cv2
import numpy as np

from rpi_logger.modules.CSICameras.csi_core.backends.picam_color import get_picam_color_format


def yuv420_to_bgr(frame: np.ndarray) -> np.ndarray:
    """
    Convert YUV420 lores frame to BGR, respecting IMX296 color bug.

    The Picamera2 lores stream outputs YUV420 format. This function converts
    it to BGR for display and shared memory transfer.

    IMPORTANT: The IMX296 kernel bug affects the ISP's understanding of the
    Bayer pattern. This propagates to YUV encoding - the U/V chrominance
    channels are computed with swapped R/B. Therefore:

    - If get_picam_color_format() == "bgr" (bug active):
      The YUV420 chrominance is also swapped, so COLOR_YUV2BGR_I420
      will produce correct BGR output (two wrongs make a right).

    - If get_picam_color_format() == "rgb" (bug fixed):
      Use COLOR_YUV2RGB_I420, then convert to BGR for consistency.

    Args:
        frame: YUV420 frame from Picamera2 lores stream

    Returns:
        BGR numpy array suitable for display or shared memory
    """
    if get_picam_color_format() == "bgr":
        # Bug active: YUV has swapped chroma, BGR conversion is correct
        return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
    else:
        # Bug fixed: Normal YUV, convert to RGB then BGR
        rgb = cv2.cvtColor(frame, cv2.COLOR_YUV2RGB_I420)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


__all__ = ["yuv420_to_bgr"]
