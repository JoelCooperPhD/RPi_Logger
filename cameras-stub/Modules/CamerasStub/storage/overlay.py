"""Overlay helpers that mirror the production Cameras module styling."""

from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np
import cv2

try:  # Picamera2 is optional for the stub runtime
    from picamera2 import MappedArray
except ImportError:  # pragma: no cover - exercised only on hardware builds
    MappedArray = None  # type: ignore[misc]


def render_frame_number(frame: np.ndarray, frame_number: int, overlay_cfg: dict) -> None:
    """Draw the capture frame number onto ``frame`` using the Cameras style."""

    font_scale = overlay_cfg.get('font_scale_base', 0.6)
    thickness = overlay_cfg.get('thickness_base', 1)

    text_color_r = overlay_cfg.get('text_color_r', 255)
    text_color_g = overlay_cfg.get('text_color_g', 255)
    text_color_b = overlay_cfg.get('text_color_b', 255)
    text_color = (text_color_r, text_color_g, text_color_b)

    margin_left = overlay_cfg.get('margin_left', 10)
    line_start_y = overlay_cfg.get('line_start_y', 30)

    border_thickness = max(1, thickness * 3)
    border_color = (0, 0, 0)
    text = f"{frame_number}"

    cv2.putText(
        frame,
        text,
        (margin_left, line_start_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        border_color,
        border_thickness,
        cv2.LINE_AA,
    )

    cv2.putText(
        frame,
        text,
        (margin_left, line_start_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        text_color,
        thickness,
        cv2.LINE_AA,
    )


class PicameraFrameOverlay:
    """Burns frame numbers into the hardware stream via Picamera2 post callbacks."""

    MAX_WARNINGS = 3

    def __init__(
        self,
        *,
        camera_id: int,
        overlay_cfg: dict,
        stream: str = "main",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if MappedArray is None:
            raise RuntimeError("Picamera2 overlay unavailable (MappedArray missing)")

        self.camera_id = camera_id
        self.overlay_cfg = overlay_cfg
        self.stream = stream
        self.logger = logger or logging.getLogger(f"PicameraFrameOverlay[{camera_id}]")

        self._active = False
        self._frame_counter = 0
        self._lock = threading.Lock()
        self._warnings = 0

    def reset(self, frame_number: int) -> None:
        with self._lock:
            self._frame_counter = max(0, int(frame_number))

    def set_active(self, active: bool) -> None:
        self._active = bool(active)

    def create_callback(self):
        if MappedArray is None:
            raise RuntimeError("Picamera2 overlay unavailable (MappedArray missing)")

        def _callback(request):
            if not self._active:
                return request

            frame_number = None
            try:
                with self._lock:
                    frame_number = self._frame_counter
                    self._frame_counter += 1

                with MappedArray(request, self.stream) as mapped:
                    render_frame_number(mapped.array, frame_number, self.overlay_cfg)
            except Exception as exc:  # pragma: no cover - defensive guard
                if self._warnings < self.MAX_WARNINGS:
                    self._warnings += 1
                    self.logger.warning(
                        "Camera %s hardware overlay failed (frame %s): %s",
                        self.camera_id,
                        frame_number if frame_number is not None else "?",
                        exc,
                    )
            return request

        return _callback


__all__ = ["render_frame_number", "PicameraFrameOverlay"]
