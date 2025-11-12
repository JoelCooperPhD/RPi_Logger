"""Frame conversion helpers shared by the Cameras stub runtime.

Color conversions follow the guidance in the official Picamera2 manual
(see https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf,
section "Media formats", pp. 32-34) which documents that YUV420 frames
are delivered as a single plane with height * 3 / 2 rows (Y plane
followed by interleaved quarter-size U and V samples).
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from .color_convert import (
    convert_rgb_frame,
    log_frame_format,
    normalize_pixel_format,
)

YUV_PLANAR_FORMATS = {
    "YUV420",
    "YUV420P",
    "I420",
}

def _sanitize_even_dimension(value: Optional[Tuple[int, int] | int], index: Optional[int] = None) -> Optional[int]:
    """Best-effort helper to coerce width/height hints into even integers."""

    if value is None:
        return None
    candidate: Any = value
    if isinstance(value, tuple) and index is not None:
        candidate = value[index]
    try:
        numeric = int(candidate)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    if numeric % 2:
        numeric -= 1
    return max(2, numeric)


def frame_to_image(
    frame: Any,
    pixel_format: str,
    *,
    size_hint: Optional[Tuple[int, int]] = None,
) -> Image.Image:
    """Convert a Picamera2 frame into a Pillow image suitable for preview/storage."""

    fmt = normalize_pixel_format(pixel_format)
    log_frame_format(frame, fmt)

    planar_candidate = getattr(frame, "ndim", None) == 2
    if planar_candidate and (fmt in YUV_PLANAR_FORMATS or _is_planar_yuv_candidate(frame, fmt)):
        array = frame if isinstance(frame, np.ndarray) else np.asarray(frame)
        if array.ndim == 2:
            rgb = _convert_yuv420_to_rgb(array, size_hint)
            return Image.fromarray(rgb, mode="RGB")

    converted_rgb = convert_rgb_frame(frame, fmt)
    if converted_rgb is not None:
        return converted_rgb

    if getattr(frame, "ndim", 0) == 2:
        return Image.fromarray(frame, mode="L")

    return Image.fromarray(np.asarray(frame)).convert("RGB")


def _is_planar_yuv_candidate(frame: Any, pixel_format: str) -> bool:
    if pixel_format.upper().startswith("YUV"):
        return True
    array = getattr(frame, "shape", None)
    if not array:
        return False
    if len(array) != 2:
        return False
    height, width = array
    return height * 2 % 3 == 0 and height > width // 4


def _convert_yuv420_to_rgb(frame: np.ndarray, size_hint: Optional[Tuple[int, int]]) -> np.ndarray:
    if frame.dtype != np.uint8:
        frame = frame.astype(np.uint8, copy=False)

    rows, stride = frame.shape
    stride = max(2, stride - (stride % 2))

    hint_width = _sanitize_even_dimension(size_hint, 0) if size_hint else None
    hint_height = _sanitize_even_dimension(size_hint, 1) if size_hint else None

    height = max(2, ((rows * 2) // 3))
    if height % 2:
        height -= 1
    if hint_height:
        height = min(height, hint_height)

    expected_rows = height * 3 // 2
    if expected_rows > rows:
        expected_rows = rows - (rows % 2)
        height = max(2, (expected_rows * 2) // 3)
        if height % 2:
            height -= 1

    width = stride
    if hint_width:
        width = min(width, hint_width)

    window = frame[:expected_rows, :width].copy(order="C")
    rgb = cv2.cvtColor(window.reshape((expected_rows, width)), cv2.COLOR_YUV2RGB_I420)

    target_w = hint_width or width
    target_h = hint_height or height
    target_w = min(target_w, rgb.shape[1])
    target_h = min(target_h, rgb.shape[0])
    if target_w != rgb.shape[1] or target_h != rgb.shape[0]:
        rgb = rgb[:target_h, :target_w]

    return rgb


__all__ = ["frame_to_image"]
