"""Shared utility functions for the Cameras module."""
from __future__ import annotations

from typing import Any, Tuple

Resolution = Tuple[int, int]


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
    except Exception:
        pass
    return default


__all__ = ["Resolution", "parse_resolution"]
