"""Simple text overlay helper for recorded frames."""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

import cv2
import numpy as np


def apply_overlay(
    frame: Any,
    *,
    text: Optional[str] = None,
    timestamp: Optional[float] = None,
    frame_number: Optional[int] = None,
) -> Any:
    """Render a small text overlay onto the frame (in-place)."""

    if frame is None:
        return frame
    if not hasattr(frame, "shape"):
        return frame
    overlay_text = text
    if overlay_text is None:
        parts = []
        if timestamp is not None:
            parts.append(_dt.datetime.fromtimestamp(timestamp).isoformat(timespec="milliseconds"))
        if frame_number is not None:
            parts.append(f"#{frame_number}")
        overlay_text = " ".join(parts)
    if not overlay_text:
        return frame

    try:
        img = frame if isinstance(frame, np.ndarray) else np.array(frame)
        cv2.putText(
            img,
            overlay_text,
            (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return img
    except Exception:
        return frame


__all__ = ["apply_overlay"]
