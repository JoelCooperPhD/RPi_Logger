"""Session path helpers for Cameras2 recordings."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir, module_filename_prefix
from rpi_logger.modules.Cameras2.runtime import CameraId


@dataclass(slots=True)
class SessionPaths:
    """Resolved filesystem layout for a single camera session."""

    root: Path
    module_dir: Path
    camera_dir: Path
    video_path: Path
    frames_dir: Path
    csv_path: Path
    metadata_path: Path


def resolve_session_paths(
    base_path: Path,
    session_id: str,
    camera_id: CameraId,
    *,
    module_name: str = "Cameras",
    module_code: str = "CAM",
    trial_number: int | None = 1,
    session_root: Path | None = None,
    per_camera_subdir: bool = True,
    suffix_on_collision: bool = True,
    logger: LoggerLike = None,
) -> SessionPaths:
    """Build session paths for a camera, mirroring the Cameras module layout."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    safe_session = _sanitize(session_id) or "session"
    safe_camera = _sanitize(camera_id.friendly_name or camera_id.stable_id) or "camera"

    if session_root is not None:
        session_root = Path(session_root)
    else:
        base_path = Path(base_path)
        session_root = base_path / safe_session
        if suffix_on_collision:
            session_root = _with_unique_suffix(session_root)

    module_dir = ensure_module_data_dir(session_root, module_name)
    camera_dir = module_dir / safe_camera if per_camera_subdir else module_dir
    camera_dir.mkdir(parents=True, exist_ok=True)

    prefix = module_filename_prefix(
        module_dir,
        module_name,
        _coerce_trial_number(trial_number),
        code=module_code,
    )
    slug = safe_camera

    video_path = camera_dir / f"{prefix}_{slug}_recording.mp4"
    frames_dir = camera_dir / "frames"
    csv_path = camera_dir / f"{prefix}_{slug}_frame_timing.csv"
    metadata_path = camera_dir / f"{prefix}_{slug}_metadata.json"

    log.debug("Resolved session paths -> %s", camera_dir)
    return SessionPaths(
        root=session_root,
        module_dir=module_dir,
        camera_dir=camera_dir,
        video_path=video_path,
        frames_dir=frames_dir,
        csv_path=csv_path,
        metadata_path=metadata_path,
    )


async def ensure_dirs(paths: SessionPaths) -> SessionPaths:
    """Ensure session directories exist using thread offload."""

    async def _mkdir(path: Path) -> None:
        await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)

    await asyncio.gather(
        _mkdir(paths.root),
        _mkdir(paths.module_dir),
        _mkdir(paths.camera_dir),
        _mkdir(paths.frames_dir),
    )
    return paths


# ---------------------------------------------------------------------------
# Internal helpers


def _sanitize(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip()) if value else ""
    return cleaned.strip("._-")


def _with_unique_suffix(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.name}_{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def _coerce_trial_number(value: int | None) -> int | None:
    try:
        numeric = int(value) if value is not None else None
    except Exception:
        return None
    if numeric is None or numeric <= 0:
        return None
    return numeric


__all__ = ["SessionPaths", "ensure_dirs", "resolve_session_paths"]
