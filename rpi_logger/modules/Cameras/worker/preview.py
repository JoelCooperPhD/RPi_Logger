"""
Preview frame processing for the worker.

Downscales frames and compresses to JPEG for efficient IPC.
"""
from __future__ import annotations

import cv2
import numpy as np


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


def decompress_preview(jpeg_data: bytes) -> np.ndarray:
    """
    Decompress JPEG bytes back to numpy array.

    Args:
        jpeg_data: JPEG-compressed bytes

    Returns:
        BGR numpy array
    """
    arr = np.frombuffer(jpeg_data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("Failed to decode preview frame")
    return frame


__all__ = ["compress_preview", "decompress_preview"]
