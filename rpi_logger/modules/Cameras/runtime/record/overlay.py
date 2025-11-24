"""Overlay helpers for record frames."""

from __future__ import annotations

import cv2
import time
from typing import Any, Optional


def apply_overlay(frame: Any, *, text: Optional[str] = None) -> Any:
    """Apply a lightweight text overlay to the frame."""

    if text is None:
        text = time.strftime("%Y-%m-%d %H:%M:%S")
    img = frame.data if hasattr(frame, "data") else frame
    try:
        cv2.putText(
            img,
            text,
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    except Exception:
        pass
    return frame


__all__ = ["apply_overlay"]
