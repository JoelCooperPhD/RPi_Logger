"""Session path helpers for per-camera recordings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rpi_logger.modules.Cameras.runtime import CameraId
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir, module_filename_prefix


@dataclass(slots=True)
class SessionPaths:
    """Resolved paths for a single camera's recording session."""

    session_root: Path
    camera_dir: Path
    video_path: Path
    timing_path: Path


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
    camera_dir = module_dir / camera_id.key.replace(":", "_") if per_camera_subdir else module_dir
    camera_dir.mkdir(parents=True, exist_ok=True)

    prefix = module_filename_prefix(session_root, module_name, trial_number)
    camera_suffix = camera_id.stable_id

    video_path = camera_dir / f"{prefix}_{camera_suffix}.avi"
    timing_path = camera_dir / f"{prefix}_{camera_suffix}_timing.csv"

    return SessionPaths(
        session_root=session_root,
        camera_dir=camera_dir,
        video_path=video_path,
        timing_path=timing_path,
    )


__all__ = ["SessionPaths", "resolve_session_paths"]
