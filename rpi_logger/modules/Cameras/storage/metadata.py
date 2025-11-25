"""Recording metadata helpers."""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rpi_logger.modules.Cameras.runtime import CameraId, ModeSelection


@dataclass(slots=True)
class RecordingMetadata:
    camera_id: CameraId
    start_time_unix: float
    end_time_unix: Optional[float] = None
    selection_preview: Optional[ModeSelection] = None
    selection_record: Optional[ModeSelection] = None
    target_fps: Optional[float] = None
    video_path: Optional[str] = None
    timing_path: Optional[str] = None


def build_metadata(
    camera_id: CameraId,
    *,
    selection_preview: Optional[ModeSelection] = None,
    selection_record: Optional[ModeSelection] = None,
    target_fps: Optional[float] = None,
    video_path: Optional[Path] = None,
    timing_path: Optional[Path] = None,
) -> RecordingMetadata:
    return RecordingMetadata(
        camera_id=camera_id,
        start_time_unix=time.time(),
        selection_preview=selection_preview,
        selection_record=selection_record,
        target_fps=target_fps,
        video_path=str(video_path) if video_path else None,
        timing_path=str(timing_path) if timing_path else None,
    )


def write_metadata(path: Path, metadata: RecordingMetadata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    mode_record = metadata.selection_record
    width = mode_record.mode.width if mode_record and mode_record.mode else None
    height = mode_record.mode.height if mode_record and mode_record.mode else None

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "camera_id",
            "backend",
            "start_time_unix",
            "end_time_unix",
            "target_fps",
            "resolution_width",
            "resolution_height",
            "video_path",
            "timing_path",
        ])
        writer.writerow([
            metadata.camera_id.stable_id,
            metadata.camera_id.backend,
            metadata.start_time_unix,
            metadata.end_time_unix or "",
            metadata.target_fps or "",
            width or "",
            height or "",
            metadata.video_path or "",
            metadata.timing_path or "",
        ])


__all__ = ["RecordingMetadata", "build_metadata", "write_metadata"]
