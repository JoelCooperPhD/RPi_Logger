"""Video recorder that supports PyAV (libx264) with OpenCV fallback."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Optional

import os
import numpy as np
import cv2

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CameraId, ModeSelection
from rpi_logger.modules.Cameras.storage.metadata import RecordingMetadata, write_metadata

try:  # pragma: no cover - optional dependency
    import av  # type: ignore

    _HAS_PYAV = True
except Exception:  # pragma: no cover - optional dependency
    av = None  # type: ignore
    _HAS_PYAV = False


@dataclass(slots=True)
class RecorderHandle:
    kind: str  # "pyav" | "opencv"
    camera_id: CameraId
    selection: ModeSelection
    queue: asyncio.Queue
    video_path: Optional[Path] = None
    container: Any = None
    stream: Any = None
    writer: Any = None
    metadata: Optional[RecordingMetadata] = None
    base_pts_ns: Optional[int] = None
    last_pts: int = 0
    record_start_ns: Optional[int] = None
    task: Optional[asyncio.Task] = None
    frames_since_flush: int = 0


class Recorder:
    """Encoder wrapper with PyAV preferred when available."""

    def __init__(
        self,
        *,
        queue_size: int = 16,
        use_pyav: Optional[bool] = None,
        logger: LoggerLike = None,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._queue_size = max(1, queue_size)
        self._use_pyav = use_pyav if use_pyav is not None else _HAS_PYAV
        # Periodically fsync so long-running recordings surface promptly on disk.
        self._flush_interval_frames = 600
        self._handles: dict[str, RecorderHandle] = {}

    # ------------------------------------------------------------------ lifecycle

    async def start(
        self,
        camera_id: CameraId,
        session_paths,
        selection: ModeSelection,
        metadata_builder,
        csv_logger=None,
    ) -> RecorderHandle:
        """Initialize encoder and return handle."""

        target_fps = selection.target_fps or selection.mode.fps
        queue = asyncio.Queue(maxsize=self._queue_size)
        handle: RecorderHandle

        if self._use_pyav and _HAS_PYAV:
            handle = await asyncio.to_thread(
                self._start_pyav, camera_id, session_paths.video_path, selection, target_fps, queue
            )
            handle.kind = "pyav"
        else:
            handle = await asyncio.to_thread(
                self._start_opencv, camera_id, session_paths.video_path, selection, target_fps, queue
            )
            handle.kind = "opencv"

        metadata = metadata_builder() if callable(metadata_builder) else None
        if isinstance(metadata, RecordingMetadata):
            handle.metadata = metadata
            handle.metadata.video_path = str(session_paths.video_path)
            handle.metadata.timing_path = str(session_paths.timing_path)
        handle.record_start_ns = time.monotonic_ns()

        task = asyncio.create_task(self._writer_loop(handle), name=f"recorder:{camera_id.key}")
        handle.task = task

        self._handles[camera_id.key] = handle
        return handle

    async def enqueue(self, handle: RecorderHandle, frame: np.ndarray, *, timestamp: float, pts_time_ns=None, color_format: str = "bgr") -> None:
        """Add frame to encoding queue with timestamp metadata."""
        try:
            await handle.queue.put((frame, timestamp, pts_time_ns, color_format))
        except asyncio.QueueFull:
            self._logger.warning("Recorder queue full for %s", handle.camera_id.key)

    async def stop(self, handle: RecorderHandle, *, metadata_csv_path=None) -> None:
        """Signal writer to stop and wait for completion."""
        await handle.queue.put(None)
        if handle.task:
            with contextlib.suppress(asyncio.CancelledError):
                await handle.task

        if handle.metadata:
            handle.metadata.end_time_unix = time.time()
            try:
                if metadata_csv_path:
                    write_metadata(Path(metadata_csv_path), handle.metadata)
            except Exception:
                self._logger.debug("Failed to write metadata", exc_info=True)

    # ------------------------------------------------------------------ Writer loop

    async def _writer_loop(self, handle: RecorderHandle) -> None:
        """Dedicated async task that consumes frames and encodes them."""
        try:
            if handle.kind == "pyav":
                await self._writer_loop_pyav(handle)
            elif handle.kind == "opencv":
                await self._writer_loop_opencv(handle)
        except asyncio.CancelledError:
            self._logger.debug("Writer loop cancelled for %s", handle.camera_id.key)
            raise
        except Exception:
            self._logger.error("Writer loop failed for %s", handle.camera_id.key, exc_info=True)
        finally:
            if handle.kind == "pyav":
                await asyncio.to_thread(self._finalize_pyav, handle)
            elif handle.kind == "opencv":
                await asyncio.to_thread(self._finalize_opencv, handle)

    async def _writer_loop_pyav(self, handle: RecorderHandle) -> None:
        """PyAV encoding loop."""
        while True:
            item = await handle.queue.get()
            if item is None:
                break
            frame, timestamp, pts_time_ns, color_format = item
            await asyncio.to_thread(self._encode_pyav, handle, frame, pts_time_ns, timestamp, color_format)

    async def _writer_loop_opencv(self, handle: RecorderHandle) -> None:
        """OpenCV encoding loop."""
        while True:
            item = await handle.queue.get()
            if item is None:
                break
            frame, _timestamp, _pts, _color_format = item
            await asyncio.to_thread(handle.writer.write, frame)
            handle.frames_since_flush += 1
            if handle.frames_since_flush >= self._flush_interval_frames:
                handle.frames_since_flush = 0
                self._fsync_path(handle.video_path)

    # ------------------------------------------------------------------ PyAV path

    def _start_pyav(
        self, camera_id: CameraId, video_path: Path, selection: ModeSelection, fps: float, queue: asyncio.Queue
    ) -> RecorderHandle:
        container = av.open(str(video_path), "w")
        fps_fraction = Fraction(fps).limit_denominator(1000)
        stream = container.add_stream("libx264", rate=fps_fraction)
        stream.width = selection.mode.width
        stream.height = selection.mode.height
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1_000_000)
        stream.codec_context.time_base = stream.time_base
        stream.codec_context.framerate = fps_fraction
        return RecorderHandle(
            kind="pyav",
            camera_id=camera_id,
            selection=selection,
            queue=queue,
            container=container,
            stream=stream,
            base_pts_ns=None,
            video_path=video_path,
        )

    def _encode_pyav(self, handle: RecorderHandle, frame: np.ndarray, pts_time_ns: Optional[int], timestamp: float, color_format: str = "bgr") -> None:
        try:
            av_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        except Exception:
            self._logger.debug("PyAV frame conversion failed", exc_info=True)
            return

        base = handle.base_pts_ns
        if base is None:
            base = pts_time_ns if pts_time_ns is not None else int(timestamp * 1_000_000_000)
            handle.base_pts_ns = base

        pts_source = pts_time_ns if pts_time_ns is not None else int(timestamp * 1_000_000_000)
        delta_ns = max(0, pts_source - base)

        elapsed_ns = max(0, time.monotonic_ns() - handle.record_start_ns) if handle.record_start_ns else delta_ns
        if delta_ns > elapsed_ns + 100_000_000:
            delta_ns = elapsed_ns

        pts = int(delta_ns / 1000)

        if pts <= handle.last_pts:
            pts = handle.last_pts + 1
        handle.last_pts = pts

        av_frame.pts = pts
        av_frame.time_base = handle.stream.time_base

        packets = handle.stream.encode(av_frame)
        for pkt in packets:
            handle.container.mux(pkt)

        handle.frames_since_flush += 1
        if handle.frames_since_flush >= self._flush_interval_frames:
            handle.frames_since_flush = 0
            self._flush_pyav(handle)

    def _finalize_pyav(self, handle: RecorderHandle) -> None:
        try:
            packets = handle.stream.encode(None)
            for pkt in packets:
                handle.container.mux(pkt)
        except Exception:
            self._logger.warning("PyAV flush failed", exc_info=True)
        try:
            handle.container.close()
        except Exception:
            self._logger.warning("PyAV close failed", exc_info=True)

    def _flush_pyav(self, handle: RecorderHandle) -> None:
        """Best-effort flush of PyAV buffers and underlying file to disk."""
        try:
            flush_fn = getattr(handle.container, "flush", None)
            if callable(flush_fn):
                flush_fn()
        except Exception:
            self._logger.debug("PyAV container flush failed", exc_info=True)
        self._fsync_path(handle.video_path)

    # ------------------------------------------------------------------ OpenCV path

    def _start_opencv(
        self, camera_id: CameraId, video_path: Path, selection: ModeSelection, fps: float, queue: asyncio.Queue
    ) -> RecorderHandle:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(video_path), fourcc, fps, (selection.mode.width, selection.mode.height))
        return RecorderHandle(
            kind="opencv",
            camera_id=camera_id,
            selection=selection,
            queue=queue,
            writer=writer,
            video_path=video_path,
        )

    def _finalize_opencv(self, handle: RecorderHandle) -> None:
        try:
            if handle.writer:
                handle.writer.release()
        except Exception:
            self._logger.warning("OpenCV release failed", exc_info=True)

    def _fsync_path(self, path: Optional[Path]) -> None:
        """Best-effort fsync to surface partially written files on disk."""
        if not path:
            return
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception:
            self._logger.debug("fsync failed for %s", path, exc_info=True)


__all__ = ["Recorder", "RecorderHandle"]
