"""
Preview frame processing for the worker.

Handles preview frame conversion, downscaling, and optional JPEG compression.
Supports both shared memory (raw BGR) and JPEG IPC paths.
"""
from __future__ import annotations

import cv2
import numpy as np

from rpi_logger.modules.Cameras.runtime.backends.picam_color import get_picam_color_format


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


def compress_preview(
    frame: np.ndarray,
    target_size: tuple[int, int],
    *,
    quality: int = 80,
    color_format: str = "bgr",
) -> bytes:
    """
    Downscale a frame and compress to JPEG.

    Args:
        frame: Input frame (BGR or RGB numpy array)
        target_size: Target (width, height) for preview
        quality: JPEG quality (1-100)
        color_format: "bgr" or "rgb" - input frame color order

    Returns:
        JPEG-compressed bytes
    """
    # Convert RGB to BGR for OpenCV (expects BGR)
    if color_format.lower() == "rgb":
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    h, w = frame.shape[:2]
    target_w, target_h = target_size

    # Resize if needed
    if w != target_w or h != target_h:
        frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)

    # Compress to JPEG
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    success, encoded = cv2.imencode(".jpg", frame, encode_params)

    if not success:
        raise RuntimeError("Failed to encode preview frame")

    return encoded.tobytes()


__all__ = ["compress_preview", "yuv420_to_bgr"]
