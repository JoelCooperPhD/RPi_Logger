"""Capability normalization helpers."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CapabilityMode, CameraCapabilities, CapabilitySource

MIN_SAFE_FPS = 5.0


def normalize_modes(raw_modes: Iterable[Dict[str, Any]]) -> List[CapabilityMode]:
    """Normalize backend-reported modes into CapabilityMode objects."""

    normalized: list[CapabilityMode] = []
    for raw in raw_modes:
        try:
            width, height = _parse_size(raw.get("size"))
            fps = float(raw.get("fps") or raw.get("frame_rate") or raw.get("framerate"))
            pixel_format = _normalize_format(raw.get("pixel_format") or raw.get("format") or "UNKNOWN")
            controls = raw.get("controls") or {}
            if fps < MIN_SAFE_FPS:
                continue
            normalized.append(CapabilityMode(size=(width, height), fps=fps, pixel_format=pixel_format, controls=controls))
        except Exception:
            continue
    return normalized


def build_capabilities(
    raw_modes: Iterable[Dict[str, Any]],
    *,
    source: CapabilitySource = CapabilitySource.PROBE,
    timestamp_ms: Optional[float] = None,
    logger: LoggerLike = None,
) -> CameraCapabilities:
    """Create CameraCapabilities with defaults chosen."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    modes = normalize_modes(raw_modes)
    capabilities = CameraCapabilities(
        modes=modes,
        timestamp_ms=timestamp_ms or (time.time() * 1000),
        source=source,
    )
    capabilities.dedupe()
    capabilities.default_preview_mode = select_default_preview(capabilities)
    capabilities.default_record_mode = select_default_record(capabilities)
    log.debug(
        "Built capabilities (%d modes) source=%s",
        len(capabilities.modes),
        capabilities.source.value,
    )
    return capabilities


def select_default_preview(capabilities: CameraCapabilities) -> Optional[CapabilityMode]:
    """Pick a sensible default preview mode capped at 640x480, honoring aspect ratio."""

    cap_w, cap_h = 640, 480
    target_ar = _aspect_ratio(capabilities.default_record_mode or (capabilities.modes[0] if capabilities.modes else None))

    under_cap = [m for m in capabilities.modes if m.width <= cap_w and m.height <= cap_h and m.fps >= 15.0]
    if under_cap:
        # Closest aspect ratio to native, then largest area under cap, then fps.
        return sorted(
            under_cap,
            key=lambda m: (_aspect_delta(m, target_ar), -(m.width * m.height), -m.fps),
        )[0]

    # If nothing under the cap, pick closest aspect ratio, smallest area to stay lightweight.
    if capabilities.modes:
        return sorted(
            capabilities.modes,
            key=lambda m: (_aspect_delta(m, target_ar), m.width * m.height, m.fps),
        )[0]
    return None


def select_default_record(capabilities: CameraCapabilities) -> Optional[CapabilityMode]:
    """Pick a sensible default record mode: highest 16:9 up to 30 fps."""

    candidates = [mode for mode in capabilities.modes if _is_16_9(mode.size)]
    if not candidates:
        candidates = capabilities.modes
    if not candidates:
        return None
    # Sort by area then fps descending, but cap at 30fps preference
    candidates = sorted(candidates, key=lambda m: (m.width * m.height, min(m.fps, 30)), reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# Internal helpers


def _parse_size(raw: Any) -> Tuple[int, int]:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return int(raw[0]), int(raw[1])
    if isinstance(raw, str) and "x" in raw.lower():
        w, h = raw.lower().split("x", 1)
        return int(w), int(h)
    raise ValueError(f"Invalid size: {raw!r}")


def _normalize_format(fmt: Any) -> str:
    if not fmt:
        return "UNKNOWN"
    text = str(fmt).upper()
    aliases = {
        "BGR24": "BGR",
        "RGB24": "RGB",
        "YUYV": "YUV422",
        "YUY2": "YUV422",
        "MJPG": "MJPEG",
    }
    return aliases.get(text, text)


def _find_size(modes: Iterable[CapabilityMode], size: Tuple[int, int], min_fps: float) -> Optional[CapabilityMode]:
    for mode in modes:
        if mode.size == size and mode.fps >= min_fps:
            return mode
    return None


def _is_16_9(size: Tuple[int, int]) -> bool:
    w, h = size
    return abs((w / h) - (16 / 9)) < 0.05


def _aspect_ratio(mode: Optional[CapabilityMode]) -> float:
    if not mode or not mode.height:
        return 0.0
    try:
        return float(mode.width) / float(mode.height)
    except Exception:
        return 0.0


def _aspect_delta(mode: CapabilityMode, target_ar: float) -> float:
    if target_ar <= 0.0:
        return 0.0
    return abs(_aspect_ratio(mode) - target_ar)
