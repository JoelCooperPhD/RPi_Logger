# Session path resolution
# Task: P3.1

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SessionPaths:
    video_path: Path
    timing_path: Path
    metadata_path: Path
    output_dir: Path


def sanitize_label(label: str) -> str:
    # TODO: Implement - Task P3.1
    raise NotImplementedError("See docs/tasks/phase3_recording.md P3.1")


def resolve_session_paths(
    base_path: Path,
    session_prefix: str,
    camera_label: str,
    per_camera_subdir: bool = False
) -> SessionPaths:
    # TODO: Implement - Task P3.1
    raise NotImplementedError("See docs/tasks/phase3_recording.md P3.1")
