"""Recording metadata helpers."""

from __future__ import annotations

import json
import platform
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import (
    CapabilityMode,
    CameraRuntimeState,
    ModeSelection,
    SelectedConfigs,
    serialize_camera_id,
)

METADATA_SCHEMA_VERSION = 1


@dataclass(slots=True)
class RecordingMetadata:
    """Structured metadata persisted alongside recordings."""

    schema: int
    session_id: str
    camera: Dict[str, Any]
    modes: Dict[str, Any]
    overlays: Dict[str, Any]
    timestamp_source: Optional[str] = None
    fps_targets: Dict[str, Any] = field(default_factory=dict)
    timing_stats: Dict[str, Any] = field(default_factory=dict)
    disk_guard: Dict[str, Any] = field(default_factory=dict)
    software: Dict[str, Any] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Builders and serializers


def build_metadata(
    session_id: str,
    camera_state: CameraRuntimeState,
    configs: SelectedConfigs,
    *,
    timestamp_source: Optional[str] = None,
    timing_stats: Optional[Dict[str, Any]] = None,
    disk_guard_status: Optional[Dict[str, Any]] = None,
    extras: Optional[Dict[str, Any]] = None,
    logger: LoggerLike = None,
) -> RecordingMetadata:
    """Assemble structured metadata from runtime state + configs."""

    log = ensure_structured_logger(logger, fallback_name=__name__)

    metadata = RecordingMetadata(
        schema=METADATA_SCHEMA_VERSION,
        session_id=session_id,
        camera=serialize_camera_id(camera_state.descriptor.camera_id),
        modes={
            "preview": _serialize_mode(configs.preview.mode),
            "record": _serialize_mode(configs.record.mode),
        },
        overlays={
            "preview": configs.preview.overlay,
            "record": configs.record.overlay,
        },
        timestamp_source=timestamp_source,
        fps_targets={
            "preview": configs.preview.target_fps,
            "record": configs.record.target_fps,
        },
        timing_stats=timing_stats or {},
        disk_guard=disk_guard_status or {},
        software=_software_info(),
        extras=extras or {},
    )
    log.debug("Built metadata for session %s camera %s", session_id, camera_state.descriptor.camera_id.key)
    return metadata


def to_json(metadata: RecordingMetadata) -> str:
    """Serialize metadata to JSON string."""

    return json.dumps(asdict(metadata), indent=2, sort_keys=True)


def from_json(text: str) -> Optional[RecordingMetadata]:
    """Parse metadata JSON into a RecordingMetadata object."""

    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return RecordingMetadata(
            schema=int(data.get("schema", METADATA_SCHEMA_VERSION)),
            session_id=str(data["session_id"]),
            camera=dict(data.get("camera") or {}),
            modes=dict(data.get("modes") or {}),
            overlays=dict(data.get("overlays") or {}),
            timestamp_source=data.get("timestamp_source"),
            fps_targets=dict(data.get("fps_targets") or {}),
            timing_stats=dict(data.get("timing_stats") or {}),
            disk_guard=dict(data.get("disk_guard") or {}),
            software=dict(data.get("software") or {}),
            extras=dict(data.get("extras") or {}),
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Internal helpers


def _serialize_mode(mode: CapabilityMode) -> Dict[str, Any]:
    return {
        "size": list(mode.size),
        "fps": mode.fps,
        "pixel_format": mode.pixel_format,
        "controls": dict(mode.controls),
    }


def _software_info() -> Dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


__all__ = ["RecordingMetadata", "METADATA_SCHEMA_VERSION", "build_metadata", "to_json", "from_json"]
