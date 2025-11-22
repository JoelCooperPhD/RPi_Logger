"""Capture settings helpers (placeholder)."""

from __future__ import annotations

from typing import Any, Dict

from rpi_logger.modules.Cameras2.runtime import ModeRequest


def build_mode_request(resolution: str, fps: float, pixel_format: str, overlay: bool = True) -> ModeRequest:
    """Construct a ModeRequest from simple values."""

    if isinstance(resolution, str) and "x" in resolution:
        width, height = resolution.lower().split("x", 1)
        size = (int(width), int(height))
    elif isinstance(resolution, (tuple, list)) and len(resolution) == 2:
        size = (int(resolution[0]), int(resolution[1]))
    else:
        size = None
    return ModeRequest(size=size, fps=fps, pixel_format=pixel_format, overlay=overlay)

