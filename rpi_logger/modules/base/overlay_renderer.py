"""Helpers for rendering consistent recording overlays across modules."""

from __future__ import annotations

from typing import Protocol

import cv2
import numpy as np


class OverlayInfo(Protocol):
    frame_number: int
    timestamp_text: str
    sensor_text: str | None


def build_overlay_text(info: OverlayInfo, cfg: dict) -> str:
    """Compose overlay text using the shared format."""
    components = [f"{info.frame_number}"]
    if cfg.get("show_recording_timestamp", True):
        components.append(info.timestamp_text)
    if cfg.get("show_sensor_timestamp", True):
        sensor = info.sensor_text
        if sensor:
            components.append(sensor)
    return " | ".join(components)


def render_overlay_bgr(frame: np.ndarray, info: OverlayInfo, cfg: dict) -> None:
    """Render overlay text onto a BGR frame (software path)."""
    if not cfg.get("show_frame_number", True):
        return

    font_scale = cfg.get("font_scale_base", 0.6)
    thickness = cfg.get("thickness_base", 1)
    text_color = (
        cfg.get("text_color_r", 0),
        cfg.get("text_color_g", 0),
        cfg.get("text_color_b", 0),
    )
    margin_left = cfg.get("margin_left", 10)
    line_start_y = cfg.get("line_start_y", 30)
    border_thickness = max(1, thickness * 3)
    border_color = (0, 0, 0)

    text = build_overlay_text(info, cfg)
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


def render_overlay_y_plane(y_plane: np.ndarray, info: OverlayInfo, cfg: dict) -> None:
    """Render overlay text on the Y plane of a YUV420 frame (hardware/YUV path)."""
    if not cfg.get("show_frame_number", True):
        return

    font_scale = cfg.get("font_scale_base", 0.6)
    thickness = cfg.get("thickness_base", 1)
    margin_left = cfg.get("margin_left", 10)
    line_start_y = cfg.get("line_start_y", 30)
    border_thickness = max(1, thickness * 3)

    text = build_overlay_text(info, cfg)

    # Border (dark)
    cv2.putText(
        y_plane,
        text,
        (margin_left, line_start_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        0,
        border_thickness,
        cv2.LINE_AA,
    )
    # Text (bright)
    cv2.putText(
        y_plane,
        text,
        (margin_left, line_start_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        255,
        thickness,
        cv2.LINE_AA,
    )


__all__ = ["OverlayInfo", "build_overlay_text", "render_overlay_bgr", "render_overlay_y_plane"]
