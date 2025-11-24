"""Timestamp-aware recorder for Cameras."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from fractions import Fraction
from typing import Any, Optional

import cv2
import numpy as np

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CameraId, ModeSelection
from rpi_logger.modules.Cameras.storage import RecordingMetadata, build_metadata, ensure_dirs

try:  # pragma: no cover - import guarded for fallback
    import av  # type: ignore

    _HAS_PYAV = True
except Exception:  # pragma: no cover - fallback to OpenCV writer
    av = None  # type: ignore
    _HAS_PYAV = False


@dataclass(slots=True)
class RecorderHandle:
    camera_id: CameraId
    csv_logger: Any
    queue: asyncio.Queue
    metadata_path: Path
    session_paths: Any
    metadata: RecordingMetadata
    kind: str  # "pyav" or "opencv"
    # PyAV fields
    container: Any | None = None
    stream: Any | None = None
    time_base: Optional[Fraction] = None
    start_pts_ns: Optional[int] = None
    last_pts: Optional[int] = None
    # OpenCV fallback
    video_writer: cv2.VideoWriter | None = None


class Recorder:
    """Async writer that prefers PyAV (timestamp-aware) with OpenCV fallback."""

    def __init__(
        self,
        *,
        queue_size: int = 8,
        use_pyav: bool = True,
        logger: LoggerLike = None,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._queue_size = queue_size
        self._use_pyav = use_pyav and _HAS_PYAV

    async def start(
        self,
        camera_id: CameraId,
        session_paths,
        selection: ModeSelection,
        metadata_builder,
        csv_logger,
    ) -> RecorderHandle:
        await ensure_dirs(session_paths)
        metadata = metadata_builder()
        await asyncio.to_thread(session_paths.metadata_path.write_text, json.dumps(metadata, default=str, indent=2))

        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        handle: RecorderHandle

        if self._use_pyav:
            handle = await self._start_pyav(camera_id, selection, session_paths, metadata, csv_logger, queue)
        else:
            handle = await self._start_opencv(camera_id, selection, session_paths, metadata, csv_logger, queue)

        asyncio.create_task(self._writer_loop(handle), name=f"recorder:{camera_id.key}")
        return handle

    async def enqueue(self, handle: RecorderHandle, frame, *, timestamp: float, pts_time_ns: Optional[int] = None) -> None:
        try:
            handle.queue.put_nowait((frame, timestamp, pts_time_ns))
        except asyncio.QueueFull:
            try:
                await handle.queue.put((frame, timestamp, pts_time_ns))
            except asyncio.CancelledError:
                return

    async def stop(self, handle: RecorderHandle) -> None:
        await handle.queue.put(None)
        # Ensure writer loop drains before returning so containers flush cleanly.
        with contextlib.suppress(Exception):
            await handle.queue.join()

    # ------------------------------------------------------------------ Internal helpers

    async def _start_pyav(
        self,
        camera_id: CameraId,
        selection: ModeSelection,
        session_paths,
        metadata: RecordingMetadata,
        csv_logger,
        queue: asyncio.Queue,
    ) -> RecorderHandle:
        """Start a PyAV container with per-frame PTS support."""

        codec_candidates = ["h264", "libx264", "mpeg4"]
        container = None
        stream = None
        last_error: Optional[str] = None
        time_base = Fraction(1, 1_000_000)  # microsecond resolution
        for codec in codec_candidates:
            try:
                container = av.open(str(session_paths.video_path), mode="w")
                stream = container.add_stream(codec)
                stream.width = selection.mode.width
                stream.height = selection.mode.height
                stream.pix_fmt = "yuv420p"
                stream.time_base = time_base
                try:
                    stream.average_rate = None  # allow VFR; avoid locking to a nominal rate
                except Exception:
                    pass
                try:
                    stream.codec_context.time_base = time_base  # type: ignore[attr-defined]
                except Exception:
                    pass
                break
            except Exception as exc:  # pragma: no cover - defensive
                last_error = str(exc)
                if container:
                    with contextlib.suppress(Exception):
                        container.close()
                container = None
                stream = None
                continue

        if not container or not stream:
            self._logger.warning("PyAV unavailable (%s); falling back to OpenCV writer", last_error or "unknown error")
            return await self._start_opencv(camera_id, selection, session_paths, metadata, csv_logger, queue)

        self._logger.info("Recording with PyAV for %s (time_base=%s)", camera_id.key, time_base)
        return RecorderHandle(
            camera_id=camera_id,
            csv_logger=csv_logger,
            queue=queue,
            metadata_path=session_paths.metadata_path,
            session_paths=session_paths,
            metadata=metadata,
            kind="pyav",
            container=container,
            stream=stream,
            time_base=time_base,
        )

    async def _start_opencv(
        self,
        camera_id: CameraId,
        selection: ModeSelection,
        session_paths,
        metadata: RecordingMetadata,
        csv_logger,
        queue: asyncio.Queue,
    ) -> RecorderHandle:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps_for_writer = selection.target_fps or selection.mode.fps or 1.0
        fps_for_writer = max(1.0, float(fps_for_writer))
        writer = cv2.VideoWriter(str(session_paths.video_path), fourcc, fps_for_writer, selection.mode.size)
        self._logger.info("Recording with OpenCV fallback for %s (fps=%s)", camera_id.key, fps_for_writer)
        return RecorderHandle(
            camera_id=camera_id,
            video_writer=writer,
            csv_logger=csv_logger,
            queue=queue,
            metadata_path=session_paths.metadata_path,
            session_paths=session_paths,
            metadata=metadata,
            kind="opencv",
        )

    async def _writer_loop(self, handle: RecorderHandle) -> None:
        if handle.kind == "pyav":
            await self._writer_loop_pyav(handle)
        else:
            await self._writer_loop_opencv(handle)

    async def _writer_loop_opencv(self, handle: RecorderHandle) -> None:
        writer = handle.video_writer
        if writer is None:
            return
        try:
            while True:
                item = await handle.queue.get()
                if item is None:
                    handle.queue.task_done()
                    break
                frame, _ts, _pts_ns = item
                await asyncio.to_thread(writer.write, frame.data if hasattr(frame, "data") else frame)
                handle.queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            with contextlib.suppress(Exception):
                writer.release()

    async def _writer_loop_pyav(self, handle: RecorderHandle) -> None:
        if not handle.container or not handle.stream or not handle.time_base:
            return
        queue = handle.queue
        try:
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    break
                frame, wall_ts, pts_ns = item
                try:
                    await asyncio.to_thread(self._encode_with_pyav, handle, frame, wall_ts, pts_ns)
                except Exception:  # pragma: no cover - defensive logging
                    self._logger.exception("PyAV encode failed for %s", handle.camera_id.key)
                queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            await asyncio.to_thread(self._finalize_pyav, handle)

    def _encode_with_pyav(self, handle: RecorderHandle, frame_obj, wall_ts: float, pts_ns: Optional[int]) -> None:
        if not handle.container or not handle.stream or not handle.time_base:
            return

        # Resolve timestamps to nanoseconds then convert to the stream time_base.
        pts_ns_resolved = pts_ns if pts_ns is not None else int(wall_ts * 1_000_000_000)
        if handle.start_pts_ns is None:
            handle.start_pts_ns = pts_ns_resolved
        base_ns = handle.start_pts_ns
        delta_ns = max(0, pts_ns_resolved - base_ns)
        pts = int(delta_ns // 1000)  # microsecond ticks
        if handle.last_pts is not None and pts <= handle.last_pts:
            pts = handle.last_pts + 1  # enforce monotonic PTS even if timestamps repeat
        handle.last_pts = pts

        np_frame = frame_obj.data if hasattr(frame_obj, "data") else frame_obj
        np_frame = np.asarray(np_frame)
        av_frame = av.VideoFrame.from_ndarray(np_frame, format="bgr24")
        av_frame.pts = pts
        av_frame.time_base = handle.time_base
        packets = handle.stream.encode(av_frame)
        for packet in packets:
            handle.container.mux(packet)

    def _finalize_pyav(self, handle: RecorderHandle) -> None:
        if handle.stream and handle.container:
            with contextlib.suppress(Exception):
                packets = handle.stream.encode(None)
                for packet in packets:
                    handle.container.mux(packet)
        if handle.container:
            with contextlib.suppress(Exception):
                handle.container.close()
