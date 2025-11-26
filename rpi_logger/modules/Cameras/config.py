"""Typed configuration helpers for Cameras."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.base.preferences import ModulePreferences
from rpi_logger.modules.Cameras.defaults import (
    DEFAULT_CAPTURE_RESOLUTION,
    DEFAULT_CAPTURE_FPS,
    DEFAULT_RECORD_FPS as _DEFAULT_RECORD_FPS,
    DEFAULT_PREVIEW_SIZE,
    DEFAULT_PREVIEW_FPS as _DEFAULT_PREVIEW_FPS,
)

Resolution = Tuple[int, int]

DEFAULT_PREVIEW_RESOLUTION: Resolution = DEFAULT_PREVIEW_SIZE
DEFAULT_PREVIEW_FPS = _DEFAULT_PREVIEW_FPS
DEFAULT_PREVIEW_FORMAT = "RGB"
DEFAULT_PREVIEW_OVERLAY = True
DEFAULT_RECORD_RESOLUTION: Resolution = DEFAULT_CAPTURE_RESOLUTION
DEFAULT_RECORD_FPS = _DEFAULT_RECORD_FPS
DEFAULT_RECORD_FORMAT = "MJPEG"
DEFAULT_RECORD_OVERLAY = True
DEFAULT_DISCOVERY_INTERVAL_MS = 2000
DEFAULT_DISCOVERY_BACKOFF_MS = 5000
DEFAULT_DISCOVERY_CACHE_TTL_MS = 600_000
DEFAULT_GUARD_DISK_FREE_GB = 1.0
DEFAULT_GUARD_CHECK_INTERVAL_MS = 5000
DEFAULT_RETENTION_MAX_SESSIONS = 10
DEFAULT_RETENTION_PRUNE_ON_START = True
DEFAULT_STORAGE_BASE_PATH = Path("./data")
DEFAULT_STORAGE_PER_CAMERA_SUBDIR = True
DEFAULT_TELEMETRY_EMIT_INTERVAL_MS = 2000
DEFAULT_TELEMETRY_INCLUDE_METRICS = True
DEFAULT_UI_AUTO_START_PREVIEW = False
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FILE = Path("./logs/cameras.log")


@dataclass(slots=True)
class PreviewSettings:
    resolution: Resolution
    fps_cap: Optional[float]
    pixel_format: str
    overlay: bool
    auto_start: bool = DEFAULT_UI_AUTO_START_PREVIEW


@dataclass(slots=True)
class RecordSettings:
    resolution: Resolution
    fps_cap: Optional[float]
    pixel_format: str
    overlay: bool


@dataclass(slots=True)
class DiscoverySettings:
    interval_ms: int
    reprobe_backoff_ms: int
    cache_ttl_ms: int


@dataclass(slots=True)
class GuardSettings:
    disk_free_gb_min: float
    check_interval_ms: int


@dataclass(slots=True)
class RetentionSettings:
    max_sessions: int
    prune_on_start: bool


@dataclass(slots=True)
class StorageSettings:
    base_path: Path
    per_camera_subdir: bool


@dataclass(slots=True)
class TelemetrySettings:
    emit_interval_ms: int
    include_metrics: bool


@dataclass(slots=True)
class UISettings:
    geometry: Optional[str]
    auto_start_preview: bool


@dataclass(slots=True)
class BackendSettings:
    picam_controls: Dict[str, Any]


@dataclass(slots=True)
class LoggingSettings:
    level: str
    file: Path


@dataclass(slots=True)
class CamerasConfig:
    preview: PreviewSettings
    record: RecordSettings
    discovery: DiscoverySettings
    guard: GuardSettings
    retention: RetentionSettings
    storage: StorageSettings
    telemetry: TelemetrySettings
    ui: UISettings
    backend: BackendSettings
    logging: LoggingSettings


# ---------------------------------------------------------------------------
# Public API


def load_config(
    preferences: ModulePreferences,
    overrides: Optional[Dict[str, Any]] = None,
    *,
    logger: LoggerLike = None,
) -> CamerasConfig:
    """Build a typed config from ModulePreferences + optional overrides."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    merged = preferences.snapshot()
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                merged[key] = value

    preview = PreviewSettings(
        resolution=_coerce_resolution(
            merged,
            ("preview.resolution", "preview_resolution", "stub_prefs.preview_resolution"),
            default=DEFAULT_PREVIEW_RESOLUTION,
            logger=log,
        ),
        fps_cap=_coerce_optional_float(
            merged,
            ("preview.fps_cap", "preview_fps", "stub_prefs.preview_fps"),
            default=DEFAULT_PREVIEW_FPS,
            logger=log,
        ),
        pixel_format=_coerce_str(
            merged,
            ("preview.format", "preview_format", "stub_prefs.preview_format"),
            DEFAULT_PREVIEW_FORMAT,
        ),
        overlay=_coerce_bool(
            merged,
            ("preview.overlay", "overlay_enabled", "stub_prefs.overlay_enabled"),
            DEFAULT_PREVIEW_OVERLAY,
        ),
        auto_start=_coerce_bool(
            merged,
            ("ui.auto_start_preview", "auto_start_preview"),
            DEFAULT_UI_AUTO_START_PREVIEW,
        ),
    )

    record = RecordSettings(
        resolution=_coerce_resolution(
            merged,
            ("record.resolution", "record_resolution", "stub_prefs.record_resolution"),
            default=DEFAULT_RECORD_RESOLUTION,
            logger=log,
        ),
        fps_cap=_coerce_optional_float(
            merged,
            ("record.fps_cap", "record_fps", "stub_prefs.record_fps"),
            default=DEFAULT_RECORD_FPS,
            logger=log,
        ),
        pixel_format=_coerce_str(
            merged,
            ("record.format", "record_format", "stub_prefs.record_format"),
            DEFAULT_RECORD_FORMAT,
        ),
        overlay=_coerce_bool(
            merged,
            ("record.overlay",),
            DEFAULT_RECORD_OVERLAY,
        ),
    )

    discovery = DiscoverySettings(
        interval_ms=_coerce_int(merged, ("discovery.interval_ms",), DEFAULT_DISCOVERY_INTERVAL_MS),
        reprobe_backoff_ms=_coerce_int(merged, ("discovery.reprobe_backoff_ms",), DEFAULT_DISCOVERY_BACKOFF_MS),
        cache_ttl_ms=_coerce_int(merged, ("discovery.cache_ttl_ms",), DEFAULT_DISCOVERY_CACHE_TTL_MS),
    )

    guard = GuardSettings(
        disk_free_gb_min=_coerce_float(merged, ("guard.disk_free_gb_min",), DEFAULT_GUARD_DISK_FREE_GB),
        check_interval_ms=_coerce_int(merged, ("guard.check_interval_ms",), DEFAULT_GUARD_CHECK_INTERVAL_MS),
    )

    retention = RetentionSettings(
        max_sessions=_coerce_int(merged, ("retention.max_sessions",), DEFAULT_RETENTION_MAX_SESSIONS),
        prune_on_start=_coerce_bool(merged, ("retention.prune_on_start",), DEFAULT_RETENTION_PRUNE_ON_START),
    )

    storage = StorageSettings(
        base_path=_coerce_path(merged, ("storage.base_path", "output_dir"), DEFAULT_STORAGE_BASE_PATH),
        per_camera_subdir=_coerce_bool(merged, ("storage.per_camera_subdir",), DEFAULT_STORAGE_PER_CAMERA_SUBDIR),
    )

    telemetry = TelemetrySettings(
        emit_interval_ms=_coerce_int(merged, ("telemetry.emit_interval_ms",), DEFAULT_TELEMETRY_EMIT_INTERVAL_MS),
        include_metrics=_coerce_bool(merged, ("telemetry.include_metrics",), DEFAULT_TELEMETRY_INCLUDE_METRICS),
    )

    ui = UISettings(
        geometry=_coerce_optional_str(merged, ("ui.geometry", "window_geometry"), default=None),
        auto_start_preview=preview.auto_start,
    )

    backend = BackendSettings(
        picam_controls=_coerce_controls(merged.get("backend.picam_controls")),
    )

    logging_settings = LoggingSettings(
        level=_coerce_str(merged, ("logging.level", "log_level"), DEFAULT_LOG_LEVEL),
        file=_coerce_path(merged, ("logging.file", "log_file"), DEFAULT_LOG_FILE),
    )

    return CamerasConfig(
        preview=preview,
        record=record,
        discovery=discovery,
        guard=guard,
        retention=retention,
        storage=storage,
        telemetry=telemetry,
        ui=ui,
        backend=backend,
        logging=logging_settings,
    )


def persist_config_sync(preferences: ModulePreferences, config: CamerasConfig) -> bool:
    """Persist selected config portions back to ModulePreferences synchronously."""

    updates = _flatten_config(config)
    return preferences.write_sync(updates)


async def persist_config_async(preferences: ModulePreferences, config: CamerasConfig) -> bool:
    """Async version of :func:`persist_config_sync`."""

    updates = _flatten_config(config)
    return await preferences.write_async(updates)


# ---------------------------------------------------------------------------
# Internal helpers


def _flatten_config(config: CamerasConfig) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    updates["preview.resolution"] = f"{config.preview.resolution[0]}x{config.preview.resolution[1]}"
    updates["preview.fps_cap"] = config.preview.fps_cap if config.preview.fps_cap is not None else ""
    updates["preview.format"] = config.preview.pixel_format
    updates["preview.overlay"] = config.preview.overlay
    updates["ui.auto_start_preview"] = config.preview.auto_start

    updates["record.resolution"] = f"{config.record.resolution[0]}x{config.record.resolution[1]}"
    updates["record.fps_cap"] = config.record.fps_cap if config.record.fps_cap is not None else ""
    updates["record.format"] = config.record.pixel_format
    updates["record.overlay"] = config.record.overlay

    updates["discovery.interval_ms"] = config.discovery.interval_ms
    updates["discovery.reprobe_backoff_ms"] = config.discovery.reprobe_backoff_ms
    updates["discovery.cache_ttl_ms"] = config.discovery.cache_ttl_ms

    updates["guard.disk_free_gb_min"] = config.guard.disk_free_gb_min
    updates["guard.check_interval_ms"] = config.guard.check_interval_ms

    updates["retention.max_sessions"] = config.retention.max_sessions
    updates["retention.prune_on_start"] = config.retention.prune_on_start

    updates["storage.base_path"] = str(config.storage.base_path)
    updates["storage.per_camera_subdir"] = config.storage.per_camera_subdir

    updates["telemetry.emit_interval_ms"] = config.telemetry.emit_interval_ms
    updates["telemetry.include_metrics"] = config.telemetry.include_metrics

    updates["ui.geometry"] = config.ui.geometry or ""

    if config.backend.picam_controls:
        updates["backend.picam_controls"] = json.dumps(config.backend.picam_controls)

    updates["logging.level"] = config.logging.level
    updates["logging.file"] = str(config.logging.file)
    return updates


def _coerce_bool(data: Dict[str, Any], keys: Tuple[str, ...], default: bool) -> bool:
    raw = _first_present(data, keys)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_optional_str(data: Dict[str, Any], keys: Tuple[str, ...], default: Optional[str]) -> Optional[str]:
    raw = _first_present(data, keys)
    if raw is None:
        return default
    text = str(raw).strip()
    return text if text else default


def _coerce_str(data: Dict[str, Any], keys: Tuple[str, ...], default: str) -> str:
    raw = _first_present(data, keys)
    if raw is None:
        return default
    text = str(raw).strip()
    return text or default


def _coerce_int(data: Dict[str, Any], keys: Tuple[str, ...], default: int) -> int:
    raw = _first_present(data, keys)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _coerce_float(data: Dict[str, Any], keys: Tuple[str, ...], default: float) -> float:
    raw = _first_present(data, keys)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _coerce_optional_float(
    data: Dict[str, Any],
    keys: Tuple[str, ...],
    default: Optional[float],
    *,
    logger,
) -> Optional[float]:
    raw = _first_present(data, keys)
    if raw is None:
        return default
    if raw == "" or raw is False:
        return None
    try:
        value = float(raw)
        return value
    except Exception:
        logger.debug("Failed to parse float from %r, using default %s", raw, default)
        return default


def _coerce_resolution(
    data: Dict[str, Any],
    keys: Tuple[str, ...],
    *,
    default: Resolution,
    logger,
) -> Resolution:
    raw = _first_present(data, keys)
    if raw is None:
        return default
    try:
        return _parse_resolution(raw)
    except Exception:
        logger.debug("Failed to parse resolution from %r, using default %s", raw, default)
        return default


def _parse_resolution(raw: Any) -> Resolution:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return int(raw[0]), int(raw[1])
    if isinstance(raw, str) and "x" in raw.lower():
        width, height = raw.lower().split("x", 1)
        return int(width.strip()), int(height.strip())
    # Allow comma separated
    if isinstance(raw, str) and "," in raw:
        width, height = raw.split(",", 1)
        return int(width.strip()), int(height.strip())
    raise ValueError(f"Unsupported resolution value: {raw!r}")


def _coerce_path(data: Dict[str, Any], keys: Tuple[str, ...], default: Path) -> Path:
    raw = _first_present(data, keys)
    if raw is None or raw == "":
        return Path(default)
    return Path(str(raw))


def _coerce_controls(raw: Any) -> Dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _first_present(data: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def as_dict(config: CamerasConfig) -> Dict[str, Any]:
    """Return a nested dict representation (useful for telemetry/debug UI)."""

    return {
        "preview": asdict(config.preview),
        "record": asdict(config.record),
        "discovery": asdict(config.discovery),
        "guard": asdict(config.guard),
        "retention": asdict(config.retention),
        "storage": {**asdict(config.storage), "base_path": str(config.storage.base_path)},
        "telemetry": asdict(config.telemetry),
        "ui": asdict(config.ui),
        "backend": {"picam_controls": config.backend.picam_controls},
        "logging": {"level": config.logging.level, "file": str(config.logging.file)},
    }


__all__ = [
    "BackendSettings",
    "CamerasConfig",
    "DiscoverySettings",
    "GuardSettings",
    "LoggingSettings",
    "PreviewSettings",
    "RecordSettings",
    "RetentionSettings",
    "StorageSettings",
    "TelemetrySettings",
    "UISettings",
    "as_dict",
    "load_config",
    "persist_config_async",
    "persist_config_sync",
]
