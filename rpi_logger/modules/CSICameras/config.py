"""Typed configuration for CSICameras."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.base.preferences import ModulePreferences, ScopedPreferences

# Type alias for resolution
Resolution = Tuple[int, int]

# Core defaults
DEFAULT_CAPTURE_RESOLUTION: Resolution = (1280, 720)
DEFAULT_CAPTURE_FPS = 30.0
DEFAULT_RECORD_FPS = 30.0
DEFAULT_PREVIEW_SIZE: Resolution = (320, 180)
DEFAULT_PREVIEW_FPS = 10.0
DEFAULT_PREVIEW_JPEG_QUALITY = 80

DEFAULT_PREVIEW_RESOLUTION: Resolution = DEFAULT_PREVIEW_SIZE
DEFAULT_PREVIEW_FORMAT = "RGB"
DEFAULT_PREVIEW_OVERLAY = True
DEFAULT_RECORD_RESOLUTION: Resolution = DEFAULT_CAPTURE_RESOLUTION
DEFAULT_RECORD_FORMAT = "RGB"  # CSI cameras use RGB
DEFAULT_RECORD_OVERLAY = True
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
DEFAULT_LOG_FILE = Path("./logs/csicameras.log")


def parse_resolution(raw: Any, default: Resolution) -> Resolution:
    """Parse resolution from list/tuple/string (e.g., '1920x1080')."""
    if raw is None:
        return default
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return (int(raw[0]), int(raw[1]))
    if isinstance(raw, str) and "x" in raw.lower():
        w, h = raw.lower().split("x", 1)
        return (int(w), int(h))
    return default


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
    auto_start_preview: bool


@dataclass(slots=True)
class BackendSettings:
    picam_controls: Dict[str, Any]


@dataclass(slots=True)
class LoggingSettings:
    level: str
    file: Path


@dataclass(slots=True)
class CSICamerasConfig:
    preview: PreviewSettings
    record: RecordSettings
    guard: GuardSettings
    retention: RetentionSettings
    storage: StorageSettings
    telemetry: TelemetrySettings
    ui: UISettings
    backend: BackendSettings
    logging: LoggingSettings

    @classmethod
    def from_preferences(
        cls,
        prefs: ScopedPreferences,
        args: Any = None,
        *,
        logger: LoggerLike = None,
    ) -> "CSICamerasConfig":
        """Build from preferences with CLI overrides."""
        merged: Dict[str, Any] = {}
        if prefs:
            snapshot = prefs.snapshot() if hasattr(prefs, 'snapshot') else {}
            merged.update(snapshot)

        # Apply CLI argument overrides
        if args is not None:
            arg_mappings = {
                "output_dir": "storage.base_path",
                "log_level": "logging.level",
            }
            for arg_name, config_key in arg_mappings.items():
                if hasattr(args, arg_name):
                    val = getattr(args, arg_name)
                    if val is not None:
                        merged[config_key] = val

        log = ensure_structured_logger(logger, fallback_name=__name__)

        preview = PreviewSettings(
            resolution=_coerce(merged, ("preview.resolution", "preview_resolution"),
                              _to_resolution, DEFAULT_PREVIEW_RESOLUTION, log),
            fps_cap=_coerce(merged, ("preview.fps_cap", "preview_fps"),
                           _to_optional_float, DEFAULT_PREVIEW_FPS, log),
            pixel_format=_coerce(merged, ("preview.format", "preview_format"),
                                _to_str, DEFAULT_PREVIEW_FORMAT),
            overlay=_coerce(merged, ("preview.overlay", "overlay_enabled"),
                           _to_bool, DEFAULT_PREVIEW_OVERLAY),
            auto_start=_coerce(merged, ("ui.auto_start_preview", "auto_start_preview"),
                              _to_bool, DEFAULT_UI_AUTO_START_PREVIEW),
        )

        record = RecordSettings(
            resolution=_coerce(merged, ("record.resolution", "record_resolution"),
                              _to_resolution, DEFAULT_RECORD_RESOLUTION, log),
            fps_cap=_coerce(merged, ("record.fps_cap", "record_fps"),
                           _to_optional_float, DEFAULT_RECORD_FPS, log),
            pixel_format=_coerce(merged, ("record.format", "record_format"),
                                _to_str, DEFAULT_RECORD_FORMAT),
            overlay=_coerce(merged, ("record.overlay",), _to_bool, DEFAULT_RECORD_OVERLAY),
        )

        guard = GuardSettings(
            disk_free_gb_min=_coerce(merged, ("guard.disk_free_gb_min",), _to_float, DEFAULT_GUARD_DISK_FREE_GB),
            check_interval_ms=_coerce(merged, ("guard.check_interval_ms",), _to_int, DEFAULT_GUARD_CHECK_INTERVAL_MS),
        )

        retention = RetentionSettings(
            max_sessions=_coerce(merged, ("retention.max_sessions",), _to_int, DEFAULT_RETENTION_MAX_SESSIONS),
            prune_on_start=_coerce(merged, ("retention.prune_on_start",), _to_bool, DEFAULT_RETENTION_PRUNE_ON_START),
        )

        storage = StorageSettings(
            base_path=_coerce(merged, ("storage.base_path", "output_dir"), _to_path, DEFAULT_STORAGE_BASE_PATH),
            per_camera_subdir=_coerce(merged, ("storage.per_camera_subdir",), _to_bool, DEFAULT_STORAGE_PER_CAMERA_SUBDIR),
        )

        telemetry = TelemetrySettings(
            emit_interval_ms=_coerce(merged, ("telemetry.emit_interval_ms",), _to_int, DEFAULT_TELEMETRY_EMIT_INTERVAL_MS),
            include_metrics=_coerce(merged, ("telemetry.include_metrics",), _to_bool, DEFAULT_TELEMETRY_INCLUDE_METRICS),
        )

        ui = UISettings(
            auto_start_preview=preview.auto_start,
        )

        backend = BackendSettings(
            picam_controls=_to_controls(merged.get("backend.picam_controls"), {}),
        )

        logging_settings = LoggingSettings(
            level=_coerce(merged, ("logging.level", "log_level"), _to_str, DEFAULT_LOG_LEVEL),
            file=_coerce(merged, ("logging.file", "log_file"), _to_path, DEFAULT_LOG_FILE),
        )

        return cls(
            preview=preview,
            record=record,
            guard=guard,
            retention=retention,
            storage=storage,
            telemetry=telemetry,
            ui=ui,
            backend=backend,
            logging=logging_settings,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Export as flat dict."""
        return {
            # Preview settings
            "preview.resolution": f"{self.preview.resolution[0]}x{self.preview.resolution[1]}",
            "preview.fps_cap": self.preview.fps_cap,
            "preview.format": self.preview.pixel_format,
            "preview.overlay": self.preview.overlay,
            "preview.auto_start": self.preview.auto_start,
            # Record settings
            "record.resolution": f"{self.record.resolution[0]}x{self.record.resolution[1]}",
            "record.fps_cap": self.record.fps_cap,
            "record.format": self.record.pixel_format,
            "record.overlay": self.record.overlay,
            # Guard settings
            "guard.disk_free_gb_min": self.guard.disk_free_gb_min,
            "guard.check_interval_ms": self.guard.check_interval_ms,
            # Retention settings
            "retention.max_sessions": self.retention.max_sessions,
            "retention.prune_on_start": self.retention.prune_on_start,
            # Storage settings
            "storage.base_path": str(self.storage.base_path),
            "storage.per_camera_subdir": self.storage.per_camera_subdir,
            # Telemetry settings
            "telemetry.emit_interval_ms": self.telemetry.emit_interval_ms,
            "telemetry.include_metrics": self.telemetry.include_metrics,
            # UI settings
            "ui.auto_start_preview": self.ui.auto_start_preview,
            # Backend settings
            "backend.picam_controls": self.backend.picam_controls,
            # Logging settings
            "logging.level": self.logging.level,
            "logging.file": str(self.logging.file),
            # Flat aliases
            "output_dir": str(self.storage.base_path),
            "log_level": self.logging.level,
        }


# Internal helpers

def _first_present(data: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
    """Return first present value for any of keys."""
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _to_bool(raw: Any, default: bool, logger=None) -> bool:
    if raw is None:
        return default
    return raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _to_str(raw: Any, default: str, logger=None) -> str:
    if raw is None:
        return default
    text = str(raw).strip()
    return text or default


def _to_int(raw: Any, default: int, logger=None) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _to_float(raw: Any, default: float, logger=None) -> float:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _to_optional_float(raw: Any, default: Optional[float], logger=None) -> Optional[float]:
    if raw is None:
        return default
    if raw == "" or raw is False:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        if logger:
            logger.debug("Failed to parse float from %r, using default %s", raw, default)
        return default


def _to_resolution(raw: Any, default: Resolution, logger=None) -> Resolution:
    if raw is None:
        return default
    result = parse_resolution(raw, default)
    if result == default and raw is not None and raw != "" and logger:
        logger.debug("Failed to parse resolution from %r, using default %s", raw, default)
    return result


def _to_path(raw: Any, default: Path, logger=None) -> Path:
    return Path(default) if raw is None or raw == "" else Path(str(raw))


def _to_controls(raw: Any, default: Dict[str, Any] = None, logger=None) -> Dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _coerce(
    data: Dict[str, Any],
    keys: Tuple[str, ...],
    coercer,
    default,
    logger=None,
):
    """Look up value by keys, apply coercer."""
    raw = _first_present(data, keys)
    return coercer(raw, default, logger)


__all__ = [
    "BackendSettings",
    "CSICamerasConfig",
    "GuardSettings",
    "LoggingSettings",
    "PreviewSettings",
    "RecordSettings",
    "RetentionSettings",
    "StorageSettings",
    "TelemetrySettings",
    "UISettings",
    "DEFAULT_CAPTURE_RESOLUTION",
    "DEFAULT_CAPTURE_FPS",
    "DEFAULT_RECORD_FPS",
    "DEFAULT_PREVIEW_SIZE",
    "DEFAULT_PREVIEW_FPS",
    "DEFAULT_PREVIEW_JPEG_QUALITY",
]
