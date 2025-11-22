"""Color conversion helpers."""

from __future__ import annotations

import cv2
import numpy as np


def _fallback_bgr_to_rgb(bgr: np.ndarray) -> np.ndarray:
    """Lightweight channel swap when cv2 is unavailable or raises."""

    return bgr[..., ::-1]


def _fallback_bgra_to_rgb(bgra: np.ndarray) -> np.ndarray:
    """Drop alpha/X channel and swap to RGB."""

    bgr = bgra[..., :3]
    return _fallback_bgr_to_rgb(bgr)


def to_rgb(frame) -> np.ndarray:
    """Convert frames to 3-channel RGB for Tk/Pillow rendering."""

    if isinstance(frame, np.ndarray):
        data = frame
    else:
        data = frame.data if hasattr(frame, "data") else frame
    if data is None:
        return data
    if not isinstance(data, np.ndarray):
        return np.array(data)

    # Grayscale input
    if data.ndim == 2 or (data.ndim == 3 and data.shape[2] == 1):
        try:
            return cv2.cvtColor(data, cv2.COLOR_GRAY2RGB)
        except Exception:
            return np.repeat(data.reshape(data.shape[0], data.shape[1], 1), 3, axis=2)

    if data.ndim == 3:
        channels = data.shape[2]

        if channels == 3:
            try:
                return cv2.cvtColor(data, cv2.COLOR_BGR2RGB)
            except Exception:
                return _fallback_bgr_to_rgb(data)

        if channels == 4:
            # Picamera2 preview defaults to XBGR/XRGB; strip the X/alpha channel.
            try:
                return cv2.cvtColor(data, cv2.COLOR_BGRA2RGB)
            except Exception:
                return _fallback_bgra_to_rgb(data)

    # If shape is unexpected, return as-is to avoid crashing the pipeline.
    return data
