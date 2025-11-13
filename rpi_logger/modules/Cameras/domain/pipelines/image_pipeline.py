"""Image acquisition and frame-routing helpers for the Cameras model."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Optional

import numpy as np

from ..model.runtime_state import CapturedFrame, FramePayload
from ...io.storage.constants import FRAME_LOG_COUNT
from ...logging_utils import ensure_structured_logger


class RollingFpsCounter:
    """Computes a rolling FPS average over a fixed time window."""

    def __init__(self, window_seconds: float = 2.0) -> None:
        self.window_seconds = max(0.1, float(window_seconds))
        self._timestamps: Deque[float] = deque()

    def tick(self, *, timestamp: Optional[float] = None) -> float:
        now = timestamp if timestamp is not None else time.perf_counter()
        self._timestamps.append(now)
        cutoff = now - self.window_seconds
        while len(self._timestamps) > 1 and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) < 2:
            return 0.0
        elapsed = self._timestamps[-1] - self._timestamps[0]
        if elapsed <= 0:
            return 0.0
        return (len(self._timestamps) - 1) / elapsed

    def reset(self) -> None:
        self._timestamps.clear()


@dataclass(slots=True)
class PipelineMetrics:
    capture_fps: float = 0.0
    process_fps: float = 0.0
    preview_fps: float = 0.0
    storage_fps: float = 0.0


class ImagePipeline:
    """Encapsulates the capture/processing queues for a single camera slot."""

    ROUTER_IDLE_SLEEP = 0.001  # seconds to yield when the router has no blocking wait

    def __init__(
        self,
        *,
        camera_index: int,
        logger,
        view_resize_checker: Optional[Callable[[], bool]] = None,
        status_refresh: Optional[Callable[[], None]] = None,
        fps_window_seconds: float = 2.0,
    ) -> None:
        self.camera_index = camera_index
        component = f"ImagePipeline.cam{camera_index}"
        self.logger = ensure_structured_logger(
            logger,
            component=component,
            fallback_name=f"{__name__}.{component}",
        )
        self._view_resize_checker = view_resize_checker or (lambda: False)
        self._status_refresh = status_refresh or (lambda: None)
        self.metrics = PipelineMetrics()
        self._capture_counter = RollingFpsCounter(fps_window_seconds)
        self._process_counter = RollingFpsCounter(fps_window_seconds)
        self._storage_counter = RollingFpsCounter(fps_window_seconds)

    def update_view_resize_checker(self, checker: Optional[Callable[[], bool]]) -> None:
        self._view_resize_checker = checker or (lambda: False)

    def reset_metrics(self, slot: Any) -> None:
        self.metrics = PipelineMetrics()
        self._capture_counter.reset()
        self._process_counter.reset()
        self._storage_counter.reset()
        slot.capture_fps = 0.0
        slot.process_fps = 0.0
        slot.preview_fps = 0.0
        slot.storage_fps = 0.0

    async def run_capture_loop(
        self,
        *,
        slot: Any,
        camera: Any,
        stop_event: asyncio.Event,
        shutdown_queue: Callable[[Optional[asyncio.Queue]], None],
        record_latency: Callable[[Any, float], None],
        log_failure: Callable[[Any, float, Exception], None],
    ) -> None:
        queue: Optional[asyncio.Queue] = getattr(slot, "capture_queue", None)
        if camera is None or queue is None:
            return

        while not stop_event.is_set():
            capture_start = time.perf_counter()
            try:
                request = await asyncio.to_thread(camera.capture_request)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive
                if stop_event.is_set():
                    break
                elapsed = time.perf_counter() - capture_start
                log_failure(slot, elapsed, exc)
                await asyncio.sleep(0.001)
                continue

            main_frame = None
            preview_frame = None
            metadata: dict[str, Any] = {}
            preview_stream = getattr(slot, "preview_stream", slot.main_stream)

            try:
                if getattr(slot, "capture_main_stream", True) and slot.main_stream:
                    main_frame = self._copy_frame(request.make_array(slot.main_stream))
                if preview_stream:
                    if preview_stream == slot.main_stream and main_frame is not None:
                        preview_frame = main_frame
                    else:
                        try:
                            preview_frame = self._copy_frame(request.make_array(preview_stream))
                        except Exception:
                            preview_frame = main_frame
                raw_metadata = request.get_metadata() or {}
                metadata = raw_metadata if isinstance(raw_metadata, dict) else dict(raw_metadata)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.error("Camera %s failed to read frame data: %s", slot.index, exc)
            finally:
                request.release()

            payload_frame = main_frame if main_frame is not None else preview_frame
            if payload_frame is None:
                continue

            queue.put_nowait(
                CapturedFrame(
                    frame=payload_frame,
                    metadata=metadata,
                    timestamp=time.time(),
                    monotonic=time.perf_counter(),
                    preview_frame=preview_frame,
                )
            )

            elapsed = time.perf_counter() - capture_start
            record_latency(slot, elapsed)
            slot.capture_fps = self._capture_counter.tick()

        shutdown_queue(queue)

    async def run_frame_router(
        self,
        *,
        slot: Any,
        stop_event: asyncio.Event,
        shutdown_queue: Callable[[Optional[asyncio.Queue]], None],
        saving_enabled: Callable[[], bool],
    ) -> None:
        queue: Optional[asyncio.Queue] = getattr(slot, "capture_queue", None)
        if queue is None:
            return

        while True:
            try:
                captured = await queue.get()
            except asyncio.CancelledError:
                break

            if captured is None:
                queue.task_done()
                break

            try:
                self._process_frame(
                    slot=slot,
                    captured=captured,
                    saving_allowed=saving_enabled(),
                )
                slot.process_fps = self._process_counter.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                if stop_event.is_set():
                    break
                self.logger.error(
                    "Frame router error (camera %s): %s",
                    slot.index,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(0.05)
            finally:
                queue.task_done()

        shutdown_queue(getattr(slot, "preview_queue", None))
        shutdown_queue(getattr(slot, "storage_queue", None))

    def _process_frame(
        self,
        *,
        slot: Any,
        captured: CapturedFrame,
        saving_allowed: bool,
    ) -> None:
        metadata = dict(captured.metadata)
        timestamp = captured.timestamp
        monotonic = captured.monotonic

        timing_result = slot.timing_tracker.next(
            metadata,
            capture_index=slot.capture_index,
            logger=self.logger,
        )
        capture_index = timing_result.capture_index
        slot.capture_index += 1

        first_frame_event = getattr(slot, "first_frame_event", None)
        if first_frame_event is not None and not first_frame_event.is_set():
            first_frame_event.set()

        timing_update = timing_result.timing_update
        if timing_update.hardware_fps and timing_update.hardware_fps > 0:
            slot.last_hardware_fps = timing_update.hardware_fps
        if timing_update.expected_interval_ns is not None:
            slot.last_expected_interval_ns = timing_update.expected_interval_ns
        if timing_update.observed_fps and timing_update.observed_fps > 0:
            slot.last_observed_fps = timing_update.observed_fps

        if capture_index < FRAME_LOG_COUNT:
            self.logger.info(
                "Frame %d: Metadata set - CaptureFrameIndex=%d, HardwareFrameNumber=%s, DroppedSinceLast=%s",
                capture_index,
                metadata.get('CaptureFrameIndex'),
                metadata.get('HardwareFrameNumber'),
                metadata.get('DroppedSinceLast'),
            )

        preview_queue = getattr(slot, "preview_queue", None)
        storage_queue = getattr(slot, "storage_queue", None)
        saving_active = bool(saving_allowed and storage_queue and slot.saving_active)
        view_is_resizing = bool(self._view_resize_checker())

        if view_is_resizing:
            slot.was_resizing = True
        elif slot.was_resizing:
            slot.was_resizing = False
            slot.preview_gate.configure(slot.preview_gate.period)

        storage_needed = bool(saving_active)
        preview_ready = bool(preview_queue and not view_is_resizing and slot.preview_enabled)

        if not storage_needed and not preview_ready:
            return

        main_array = captured.frame
        if main_array is None:
            return

        limiter = getattr(slot, "frame_rate_gate", None)
        if limiter is not None and not limiter.should_emit(monotonic):
            return

        preview_frame = captured.preview_frame if captured.preview_frame is not None else main_array
        if preview_frame is not None:
            self._record_stream_size(slot, preview_frame)
        preview_pixel_format = slot.preview_format or slot.main_format
        if preview_frame is main_array:
            preview_pixel_format = slot.main_format or preview_pixel_format

        storage_enqueued = False
        if storage_queue and storage_needed:
            payload = FramePayload(
                frame=main_array,
                timestamp=timestamp,
                monotonic=monotonic,
                metadata=metadata,
                pixel_format=slot.main_format or slot.preview_format,
                stream=slot.main_stream,
                capture_index=capture_index,
                hardware_frame_number=timing_result.hardware_frame_number,
                dropped_since_last=timing_result.dropped_since_last,
                sensor_timestamp_ns=timing_result.sensor_timestamp_ns,
            )
            self._offer_queue(
                storage_queue,
                payload,
                drop_hook=lambda: self._record_storage_drop(slot),
            )
            slot.storage_fps = self._storage_counter.tick()
            storage_enqueued = True

        emit_preview = False
        if preview_ready:
            stride = max(1, slot.preview_stride)
            emit_preview = ((capture_index - slot.preview_stride_offset) % stride) == 0

        if not storage_enqueued and not emit_preview:
            return

        if preview_queue and emit_preview and preview_frame is not None and slot.preview_enabled:
            payload = FramePayload(
                frame=preview_frame,
                timestamp=timestamp,
                monotonic=monotonic,
                metadata=metadata,
                pixel_format=preview_pixel_format,
                stream=slot.preview_stream,
                capture_index=capture_index,
                hardware_frame_number=timing_result.hardware_frame_number,
                dropped_since_last=timing_result.dropped_since_last,
                sensor_timestamp_ns=timing_result.sensor_timestamp_ns,
            )
            self._offer_queue(preview_queue, payload)

        # Preview frames are emitted after storage so the stretch/skip logic never starves disk writes.

    def _record_stream_size(self, slot: Any, frame: Any) -> None:
        if getattr(slot, "preview_stream_size", None):
            return
        height = width = None
        if getattr(frame, "ndim", 0) == 2:
            rows, stride = frame.shape
            width = stride - (stride % 2)
            height = ((rows * 2) // 3)
            height -= height % 2
        elif getattr(frame, "ndim", 0) == 3:
            height, width = frame.shape[:2]
        if width and height:
            width = max(2, int(width))
            height = max(2, int(height))
            slot.preview_stream_size = (int(width), int(height))

    @staticmethod
    def _copy_frame(frame: Any) -> Any:
        if frame is None:
            return None
        try:
            return np.array(frame, copy=True)
        except Exception:
            return frame

    def _offer_queue(
        self,
        queue: asyncio.Queue,
        payload: FramePayload,
        *,
        drop_hook: Optional[Callable[[], None]] = None,
    ) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.task_done()
                if drop_hook:
                    drop_hook()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:  # pragma: no cover - defensive
                pass

    def _record_storage_drop(self, slot: Any) -> None:
        slot.storage_drop_since_last += 1
        slot.storage_drop_total += 1
        if slot.storage_drop_total <= 5 or slot.storage_drop_total % 25 == 0:
            self.logger.warning(
                "Storage queue drop detected on cam %s (total %d, buffer=%d)",
                slot.index,
                slot.storage_drop_total,
                slot.storage_queue_size,
            )
        self._status_refresh()


__all__ = ["ImagePipeline", "PipelineMetrics", "RollingFpsCounter"]
