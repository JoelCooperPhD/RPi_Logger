"""RGB/ARGB frame conversion helpers for the Cameras module."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
from PIL import Image

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)

_LOGGED_FORMATS: set[str] = set()

RAW_MODE_LOOKUP = {
    "RGB888": "BGR",
    "BGR888": "RGB",
    "XBGR8888": "RGBX",
    "XRGB8888": "BGRX",
    "ABGR8888": "RGBA",
    "ARGB8888": "BGRA",
}


def normalize_pixel_format(pixel_format: Optional[str]) -> str:
    if not pixel_format:
        return ""
    fmt = str(pixel_format).strip().upper()
    if not fmt:
        return ""
    fmt = fmt.split('/', 1)[0]
    return fmt.strip()


def log_frame_format(frame: Any, fmt: str) -> None:
    if not fmt or fmt in _LOGGED_FORMATS:
        return
    shape = getattr(frame, "shape", None)
    dtype = getattr(frame, "dtype", None)
    ndim = getattr(frame, "ndim", None)
    logger.info(
        "frame_to_image format=%s ndim=%s shape=%s dtype=%s",
        fmt,
        ndim,
        shape,
        dtype,
    )
    _LOGGED_FORMATS.add(fmt)


def convert_rgb_frame(frame: Any, pixel_format: str) -> Optional[Image.Image]:
    if getattr(frame, "ndim", None) != 3:
        return None

    channels = frame.shape[2]
    if channels not in (3, 4):
        return None

    fmt = normalize_pixel_format(pixel_format)
    pil_image = _rgb_from_interleaved(frame, fmt)
    if pil_image is not None:
        return pil_image

    if channels == 3:
        if getattr(frame, "dtype", None) == np.uint8:
            return Image.fromarray(frame[..., ::-1], mode="RGB")
        return Image.fromarray(frame, mode="RGB")

    if channels == 4:
        if getattr(frame, "dtype", None) == np.uint8:
            return Image.fromarray(frame[..., [2, 1, 0, 3]], mode="RGBA").convert("RGB")
        return Image.fromarray(frame, mode="RGBA").convert("RGB")

    return None


def _rgb_from_interleaved(frame: np.ndarray, fmt: str) -> Optional[Image.Image]:
    raw_mode = RAW_MODE_LOOKUP.get(fmt)
    if raw_mode is None:
        return None

    buffer = frame if frame.flags.c_contiguous else np.ascontiguousarray(frame)
    height, width = buffer.shape[:2]
    stride = buffer.strides[0]

    try:
        image = Image.frombuffer(
            "RGB",
            (width, height),
            buffer,
            "raw",
            raw_mode,
            stride,
            1,
        )
    except ValueError:
        return None

    if image.mode != "RGB":
        return image.convert("RGB")
    return image.copy()


__all__ = [
    "convert_rgb_frame",
    "log_frame_format",
    "normalize_pixel_format",
]
