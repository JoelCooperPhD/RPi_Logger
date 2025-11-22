"""Lightweight recorder for Cameras2."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras2.runtime import CameraId, ModeSelection
from rpi_logger.modules.Cameras2.storage import RecordingMetadata, build_metadata, ensure_dirs


@dataclass(slots=True)
class RecorderHandle:
    camera_id: CameraId
    video_writer: cv2.VideoWriter
    csv_logger: Any
    queue: asyncio.Queue
    metadata_path: Path
    session_paths: Any
    metadata: RecordingMetadata


class Recorder:
    """Async writer wrapping OpenCV VideoWriter and CSV logger."""

    def __init__(
        self,
        *,
        queue_size: int = 8,
        logger: LoggerLike = None,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._queue_size = queue_size

    async def start(
        self,
        camera_id: CameraId,
        session_paths,
        selection: ModeSelection,
        metadata_builder,
        csv_logger,
    ) -> RecorderHandle:
        await ensure_dirs(session_paths)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps_for_writer = selection.target_fps or selection.mode.fps or 1.0
        fps_for_writer = max(1.0, float(fps_for_writer))
        writer = cv2.VideoWriter(str(session_paths.video_path), fourcc, fps_for_writer, selection.mode.size)
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        metadata = metadata_builder()
        await asyncio.to_thread(session_paths.metadata_path.write_text, json.dumps(metadata, default=str, indent=2))
        handle = RecorderHandle(
            camera_id=camera_id,
            video_writer=writer,
            csv_logger=csv_logger,
            queue=queue,
            metadata_path=session_paths.metadata_path,
            session_paths=session_paths,
            metadata=metadata,
        )
        asyncio.create_task(self._writer_loop(handle), name=f"recorder:{camera_id.key}")
        return handle

    async def enqueue(self, handle: RecorderHandle, frame, *, timestamp: float) -> None:
        try:
            handle.queue.put_nowait((frame, timestamp))
        except asyncio.QueueFull:
            try:
                await handle.queue.put((frame, timestamp))
            except asyncio.CancelledError:
                return

    async def stop(self, handle: RecorderHandle) -> None:
        await handle.queue.put(None)

    async def _writer_loop(self, handle: RecorderHandle) -> None:
        writer = handle.video_writer
        try:
            while True:
                item = await handle.queue.get()
                if item is None:
                    break
                frame, ts = item
                await asyncio.to_thread(writer.write, frame.data if hasattr(frame, "data") else frame)
                handle.queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            writer.release()
            handle.queue.task_done()
