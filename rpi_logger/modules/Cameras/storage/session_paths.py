"""Session path helpers for per-camera recordings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rpi_logger.modules.Cameras.camera_core import CameraId
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir, module_filename_prefix


@dataclass(slots=True)
class SessionPaths:
    """Resolved paths for a single camera's recording session."""

    session_root: Path
    camera_dir: Path
    video_path: Path
    timing_path: Path


def _sanitize_for_filesystem(name: str, max_length: int = 50) -> str:
    """Sanitize a name for safe use in file/directory names.

    - Replaces spaces and problematic characters with underscores
    - Removes characters that are invalid in filenames
    - Truncates to max_length
    """
    # Replace spaces and common separators with underscores
    sanitized = re.sub(r'[\s\-/\\:]+', '_', name)
    # Remove any remaining problematic characters (keep alphanumeric, underscore, dot)
    sanitized = re.sub(r'[^\w.]', '', sanitized)
    # Collapse multiple underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Strip leading/trailing underscores
    sanitized = sanitized.strip('_')
    # Truncate if needed
    return sanitized[:max_length] if sanitized else "camera"


def _build_camera_label(camera_id: CameraId) -> str:
    """Build a human-readable label for camera directory/file naming.

    Uses friendly_name if available, with a short stable_id suffix for uniqueness.
    Falls back to stable_id if no friendly_name is set.
    """
    if camera_id.friendly_name:
        # Use friendly name as primary, add short stable_id suffix for uniqueness
        base_name = _sanitize_for_filesystem(camera_id.friendly_name)
        # Take first 8 chars of stable_id for uniqueness (handles duplicate names)
        short_id = camera_id.stable_id[:8] if len(camera_id.stable_id) > 8 else camera_id.stable_id
        return f"{base_name}_{short_id}"
    else:
        # Fallback to stable_id only
        return _sanitize_for_filesystem(camera_id.stable_id)


def resolve_session_paths(
    session_dir: Path,
    camera_id: CameraId,
    *,
    module_name: str = "Cameras",
    trial_number: int = 1,
    per_camera_subdir: bool = True,
) -> SessionPaths:
    """Build a deterministic directory + filename layout and ensure it exists."""

    session_root = Path(session_dir)
    module_dir = ensure_module_data_dir(session_root, module_name)

    # Build camera label from friendly name (e.g., "FaceTime_HD_Camera_0D0B7853")
    camera_label = _build_camera_label(camera_id)
    camera_dir = module_dir / camera_label if per_camera_subdir else module_dir
    camera_dir.mkdir(parents=True, exist_ok=True)

    prefix = module_filename_prefix(session_root, module_name, trial_number, code="CAM")

    video_path = camera_dir / f"{prefix}_{camera_label}.avi"
    timing_path = camera_dir / f"{prefix}_{camera_label}_timing.csv"

    return SessionPaths(
        session_root=session_root,
        camera_dir=camera_dir,
        video_path=video_path,
        timing_path=timing_path,
    )


__all__ = ["SessionPaths", "resolve_session_paths"]
