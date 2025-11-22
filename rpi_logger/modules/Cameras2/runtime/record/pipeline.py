"""Record pipeline for Cameras2."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Callable

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras2.runtime import CameraId, ModeSelection
from rpi_logger.modules.Cameras2.runtime.metrics import FPSCounter, TimingTracker
from rpi_logger.modules.Cameras2.runtime.record.fps_tracker import RecordFPSTracker
from rpi_logger.modules.Cameras2.runtime.record.recorder import Recorder
from rpi_logger.modules.Cameras2.runtime.record.overlay import apply_overlay
from rpi_logger.modules.Cameras2.runtime.record.csv_logger import CSVLogger, CSVRecord
from rpi_logger.modules.Cameras2.runtime.record.timing import FrameTimingTracker
from rpi_logger.modules.Cameras2.storage import DiskGuard


class RecordPipeline:
    """Consumes frames from record queue, applies overlay, and queues to recorder."""

    def __init__(
        self,
        recorder: Recorder,
        disk_guard: DiskGuard,
        *,
        logger: LoggerLike = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._recorder = recorder
        self._disk_guard = disk_guard
        self._tasks: dict[str, asyncio.Task] = {}
        self._metrics: dict[str, dict[str, float | int]] = {}
        self._csv_loggers: dict[str, CSVLogger] = {}
        self._timers: dict[str, FrameTimingTracker] = {}
        self._frame_counters: dict[str, int] = {}
        self._clock = clock or time.monotonic

    def start(
        self,
        camera_id: CameraId,
        queue: asyncio.Queue,
        selection: ModeSelection,
        *,
        session_paths,
        metadata_builder,
        csv_logger=None,
        trial_number: int | None = None,
    ) -> None:
        key = camera_id.key
        if key in self._tasks:
            return
        if key not in self._timers:
            self._timers[key] = FrameTimingTracker()
        if key not in self._frame_counters:
            self._frame_counters[key] = 0
        if csv_logger is None:
            csv_logger = CSVLogger(trial_number=trial_number, camera_label=key, logger=self._logger)
        self._csv_loggers[key] = csv_logger

        task_init = asyncio.create_task(self._start_logger(csv_logger, session_paths), name=f"csv:{key}")

        task = asyncio.create_task(
            self._loop(camera_id, queue, selection, session_paths, metadata_builder, csv_logger, task_init),
            name=f"record:{key}",
        )
        self._tasks[key] = task
        task.add_done_callback(lambda _: self._tasks.pop(key, None))
        self._logger.info("Record pipeline started for %s", key)
        self._metrics[key] = {
            "frames_written": 0,
            "skipped_fps_cap": 0,
            "record_fps_instant": 0.0,
            "record_fps_avg": 0.0,
            "record_ingest_fps_avg": 0.0,
        }

    async def stop(self, camera_id: CameraId) -> None:
        task = self._tasks.pop(camera_id.key, None)
        self._metrics.pop(camera_id.key, None)
        csv_logger = self._csv_loggers.pop(camera_id.key, None)
        self._timers.pop(camera_id.key, None)
        self._frame_counters.pop(camera_id.key, None)
        if not task:
            if csv_logger:
                await csv_logger.stop()
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if csv_logger:
            await csv_logger.stop()
        self._logger.info("Record pipeline stopped for %s", camera_id.key)

    async def _start_logger(self, csv_logger: CSVLogger, session_paths) -> None:
        try:
            await csv_logger.start(session_paths.csv_path)
        except Exception:  # pragma: no cover - defensive logging
            self._logger.exception("Failed to start CSV logger for %s", session_paths.csv_path)

    async def _loop(
        self,
        camera_id: CameraId,
        queue: asyncio.Queue,
        selection: ModeSelection,
        session_paths,
        metadata_builder,
        csv_logger,
        csv_task: asyncio.Task,
    ) -> None:
        key = camera_id.key
        fps_counter = FPSCounter()
        ingest_counter = FPSCounter()
        timing = TimingTracker()
        fps_tracker = RecordFPSTracker()
        frame_timing = self._timers.get(key) or FrameTimingTracker()
        capture_index = self._frame_counters.get(key, 0)

        preflight = await self._disk_guard.check_before_start(session_paths.root)
        if not preflight.ok:
            self._logger.warning("Record start blocked by disk guard for %s", key)
            return

        # Ensure CSV logger is ready before recording.
        with contextlib.suppress(Exception):
            await csv_task

        recorder_handle = await self._recorder.start(camera_id, session_paths, selection, metadata_builder, None)
        target_rate = float(selection.target_fps or 0.0)
        bucket_capacity = max(1.0, target_rate)
        last_tick = self._clock()
        allowance = 1.0  # allow the first frame through immediately
        try:
            while True:
                frame = await queue.get()
                if frame is None:
                    break
                tick_now = self._clock()
                elapsed = max(0.0, tick_now - last_tick)
                last_tick = tick_now

                ingest_snapshot = ingest_counter.update()
                self._metrics[key]["record_ingest_fps_avg"] = round(ingest_snapshot.average, 2)

                if target_rate > 0.0:
                    allowance = min(bucket_capacity, allowance + elapsed * target_rate)
                    if allowance < 1.0:
                        self._metrics[key]["skipped_fps_cap"] = self._metrics[key].get("skipped_fps_cap", 0) + 1
                        queue.task_done()
                        continue
                    allowance -= 1.0

                wall_now = time.time()
                snap = fps_counter.update(wall_now)
                timing.record(wall_now)
                fps_tracker.record_frame(wall_now)
                self._metrics[key]["record_fps_instant"] = round(snap.instant, 2)
                self._metrics[key]["record_fps_avg"] = round(snap.average, 2)

                timing_update = frame_timing.update(
                    frame_number=getattr(frame, "frame_number", None),
                    sensor_timestamp=getattr(frame, "timestamp", None),
                    monotonic_time=tick_now,
                )
                storage_queue_drops = csv_logger.queue_overflow_drops if csv_logger else 0
                if csv_logger:
                    csv_logger.log_frame(
                        CSVRecord(
                            trial=csv_logger.trial_number,
                            frame_number=capture_index,
                            write_time_unix=wall_now,
                            monotonic_time=tick_now,
                            sensor_timestamp_ns=timing_update.sensor_timestamp_ns,
                            hardware_frame_number=timing_update.hardware_frame_number,
                            dropped_since_last=timing_update.dropped_since_last,
                            total_hardware_drops=timing_update.total_hardware_drops,
                            storage_queue_drops=storage_queue_drops,
                        )
                    )
                capture_index += 1

                # Apply lightweight overlay if requested
                if selection.overlay:
                    frame = apply_overlay(frame)

                await self._recorder.enqueue(recorder_handle, frame, timestamp=wall_now)
                self._metrics[key]["frames_written"] = self._metrics[key].get("frames_written", 0) + 1
                queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive logging
            self._logger.exception("Record pipeline error for %s", key)
        finally:
            self._frame_counters[key] = capture_index
            await self._recorder.stop(recorder_handle)
            if not queue.empty():
                with contextlib.suppress(Exception):
                    queue.task_done()

    def metrics(self, camera_id: CameraId) -> dict[str, float | int]:
        return dict(self._metrics.get(camera_id.key, {}))
