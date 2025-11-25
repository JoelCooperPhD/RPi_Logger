"""Recording pipeline: timing, overlay, CSV, and recorder enqueue."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

import numpy as np

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CameraId, ModeSelection
from rpi_logger.modules.Cameras.runtime.metrics import FPSCounter
from rpi_logger.modules.Cameras.runtime.record.csv_logger import CSVLogger, CSVRecord
from rpi_logger.modules.Cameras.runtime.record.overlay import apply_overlay
from rpi_logger.modules.Cameras.runtime.record.recorder import Recorder
from rpi_logger.modules.Cameras.runtime.record.timing import FrameTimingTracker
from rpi_logger.modules.Cameras.storage import DiskGuard, resolve_session_paths
from rpi_logger.modules.Cameras.storage.metadata import build_metadata
from rpi_logger.modules.Cameras.storage.session_paths import SessionPaths
from rpi_logger.modules.Cameras.runtime.tasks import TaskManager


class RecordPipeline:
    """Consumes frames from record queue and forwards to recorder with logging."""

    def __init__(
        self,
        recorder: Recorder,
        disk_guard: DiskGuard,
        *,
        logger: LoggerLike = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._recorder = recorder
        self._disk_guard = disk_guard
        self._clock = clock
        self._task_manager = TaskManager(logger=self._logger)
        self._states: dict[str, dict[str, Any]] = {}
        self._fps = FPSCounter()

    # ------------------------------------------------------------------
    def start(
        self,
        camera_id: CameraId,
        queue: asyncio.Queue,
        selection: ModeSelection,
        *,
        session_paths: SessionPaths,
        metadata_builder: Optional[Callable[[], Any]] = None,
        csv_logger: Optional[CSVLogger] = None,
        trial_number: Optional[int] = None,
    ) -> None:
        key = camera_id.key
        if csv_logger is None:
            csv_logger = CSVLogger(trial_number=trial_number, camera_label=key, flush_every=16)

        state = {
            "queue": queue,
            "selection": selection,
            "paths": session_paths,
            "csv": csv_logger,
            "trial": trial_number,
            "timing": FrameTimingTracker(),
            "last_emit": 0.0,
            "drops": 0,
            "handle": None,
            "metadata_builder": metadata_builder or (lambda: build_metadata(camera_id)),
        }
        self._states[key] = state
        self._task_manager.create(f"record:{key}", self._loop(camera_id))
        self._logger.info("Record pipeline started for %s", key)

    async def stop(self, camera_id: CameraId) -> None:
        key = camera_id.key
        await self._task_manager.cancel(f"record:{key}")
        state = self._states.pop(key, None)
        if not state:
            return
        handle = state.get("handle")
        try:
            if handle:
                await self._recorder.stop(handle)
        finally:
            csv_logger: CSVLogger = state.get("csv")
            if csv_logger:
                await csv_logger.stop()

    # ------------------------------------------------------------------
    async def _loop(self, camera_id: CameraId) -> None:
        key = camera_id.key
        state = self._states[key]
        queue: asyncio.Queue = state["queue"]
        selection: ModeSelection = state["selection"]
        csv_logger: CSVLogger = state["csv"]
        timing: FrameTimingTracker = state["timing"]
        paths: SessionPaths = state["paths"]

        await csv_logger.start(paths.timing_path)

        metadata_builder = state["metadata_builder"]
        handle = await self._recorder.start(
            camera_id,
            paths,
            selection,
            metadata_builder=lambda: metadata_builder(),
            csv_logger=csv_logger,
        )
        state["handle"] = handle

        try:
            while True:
                frame = await queue.get()
                if frame is None:
                    queue.task_done()
                    break
                now = self._clock()

                frame_number = getattr(frame, "frame_number", 0)
                monotonic_ns = getattr(frame, "monotonic_ns", int(now * 1_000_000_000))
                sensor_ts = getattr(frame, "sensor_timestamp_ns", None)
                wall_time = getattr(frame, "timestamp", time.time())
                storage_q_drops = getattr(frame, "storage_queue_drops", 0)
                hardware_frame_number = getattr(frame, "hardware_frame_number", None)
                color_format = str(getattr(frame, "color_format", "bgr") or "bgr").lower()

                update = timing.update(
                    frame_number=frame_number or 0,
                    sensor_timestamp_ns=sensor_ts,
                    monotonic_time_ns=monotonic_ns,
                    write_time_unix=wall_time if isinstance(wall_time, (int, float)) else time.time(),
                    hardware_frame_number=hardware_frame_number,
                    storage_queue_drops=storage_q_drops,
                )

                data = getattr(frame, "data", frame)
                if color_format.startswith("rgb") and isinstance(data, np.ndarray):
                    try:
                        data = data[..., :3][:, :, ::-1]
                    except Exception:
                        data = data[..., ::-1]
                    color_format = "bgr"
                if selection.overlay:
                    data = apply_overlay(data, timestamp=wall_time, frame_number=frame_number)

                csv_logger.log_frame(
                    CSVRecord(
                        trial=state["trial"],
                        frame_number=update.frame_number,
                        write_time_unix=update.write_time_unix,
                        monotonic_time=update.monotonic_time_ns / 1_000_000_000,
                        sensor_timestamp_ns=update.sensor_timestamp_ns,
                        hardware_frame_number=update.hardware_frame_number,
                        dropped_since_last=update.dropped_since_last,
                        total_hardware_drops=update.total_hardware_drops,
                        storage_queue_drops=update.storage_queue_drops,
                    )
                )
                if len(csv_logger._rows) >= csv_logger._flush_every:  # type: ignore[attr-defined]
                    await csv_logger.flush()

                await self._recorder.enqueue(
                    handle,
                    data,
                    timestamp=wall_time if isinstance(wall_time, (int, float)) else time.time(),
                    pts_time_ns=sensor_ts or monotonic_ns,
                    color_format=color_format,
                )
                queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            try:
                await csv_logger.flush()
            finally:
                if handle:
                    await self._recorder.stop(handle, metadata_csv_path=paths.metadata_csv_path)
            queue.put_nowait(None)

    def metrics(self, camera_id: CameraId) -> dict[str, Any]:
        state = self._states.get(camera_id.key)
        if not state:
            return {}
        csv_logger: CSVLogger = state["csv"]
        return {
            "record_fps_avg": round(self._fps.update().average, 2),
            "record_dropped": state.get("drops", 0),
            "record_csv_pending": len(csv_logger._rows),  # type: ignore[attr-defined]
        }


__all__ = ["RecordPipeline"]
