"""Shared utility functions for the Cameras module.

Keep this module lightweight - it's imported by worker subprocesses.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple

Resolution = Tuple[int, int]


@dataclass(slots=True)
class CameraMetrics:
    """Metrics snapshot for a camera.

    Uses consistent field naming across the module.
    """
    state: str
    is_recording: bool
    fps_capture: float
    fps_encode: float
    fps_preview: float
    frames_captured: int
    frames_recorded: int
    target_record_fps: float
    capture_wait_ms: float
    preview_queue: int = 0
    record_queue: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for UI consumption."""
        return asdict(self)


def parse_resolution(raw: Any, default: Resolution) -> Resolution:
    """Parse resolution from various formats.

    Supports:
    - Tuple/list: (1280, 720) or [1280, 720]
    - String with 'x': "1280x720" or "1280X720"
    - String with comma: "1280, 720"

    Returns the default if parsing fails.
    """
    if raw is None or raw == "":
        return default
    try:
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            return int(raw[0]), int(raw[1])
        if isinstance(raw, str):
            s = raw.strip()
            if "x" in s.lower():
                w, h = s.lower().split("x", 1)
                return int(w.strip()), int(h.strip())
            if "," in s:
                w, h = s.split(",", 1)
                return int(w.strip()), int(h.strip())
    except (ValueError, TypeError, AttributeError):
        pass
    return default


def parse_fps(raw: Any, default: float) -> float:
    """Parse FPS from string or number.

    Returns the default if parsing fails.
    """
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def parse_bool(raw: Any, default: bool) -> bool:
    """Parse boolean from various formats.

    Truthy strings: "true", "1", "yes", "on"
    """
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def extract_settings(
    saved: Optional[Dict[str, Any]],
    defaults: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract typed settings from saved dict with defaults.

    Handles resolution, fps, and boolean parsing.

    Expected keys in defaults:
    - preview_resolution: Resolution
    - preview_fps: float
    - record_resolution: Resolution
    - record_fps: float
    - overlay: bool
    """
    if not saved:
        return dict(defaults)

    result = {}

    # Resolution fields
    for key in ("preview_resolution", "record_resolution"):
        if key in defaults:
            result[key] = parse_resolution(
                saved.get(key, ""),
                defaults[key]
            )

    # FPS fields
    for key in ("preview_fps", "record_fps"):
        if key in defaults:
            result[key] = parse_fps(
                saved.get(key, ""),
                defaults[key]
            )

    # Boolean fields
    for key in ("overlay",):
        if key in defaults:
            result[key] = parse_bool(
                saved.get(key, ""),
                defaults[key]
            )

    return result


__all__ = [
    "CameraMetrics",
    "Resolution",
    "extract_settings",
    "parse_bool",
    "parse_fps",
    "parse_resolution",
]
