"""Capture and routing pipeline for USB cameras."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

from ..model import CapturedFrame, FrameGate, FramePayload, RollingFpsCounter
from rpi_logger.core.logging_utils import ensure_structured_logger


class USBCapturePipeline:
    """Encapsulates the capture/processing queues for a single USB camera slot."""

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
        component = f"USBCapturePipeline.cam{camera_index}"
        self.logger = ensure_structured_logger(
            logger,
            component=component,
            fallback_name=f"{__name__}.{component}",
        )
        self._view_resize_checker = view_resize_checker or (lambda: False)
        self._status_refresh = status_refresh or (lambda: None)
        self._capture_counter = RollingFpsCounter(fps_window_seconds)
        self._process_counter = RollingFpsCounter(fps_window_seconds)

    def update_view_resize_checker(self, checker: Optional[Callable[[], bool]]) -> None:
        self._view_resize_checker = checker or (lambda: False)

    def reset_metrics(self, slot: Any) -> None:
        self._capture_counter.reset()
        self._process_counter.reset()
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

        pause_event = getattr(slot, "capture_active_event", None)
        idle_event = getattr(slot, "capture_idle_event", None)
        consecutive_failures = 0

        while not stop_event.is_set():
            if pause_event is not None and not pause_event.is_set():
                if idle_event and not idle_event.is_set():
                    idle_event.set()
                if stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(pause_event.wait(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                if idle_event and idle_event.is_set():
                    idle_event.clear()
                continue
            if idle_event and idle_event.is_set():
                idle_event.clear()

            capture_start = time.perf_counter()
            try:
                ok, frame, metadata = await asyncio.to_thread(camera.read)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive logging
                if stop_event.is_set():
                    break
                elapsed = time.perf_counter() - capture_start
                log_failure(slot, elapsed, exc)
                await asyncio.sleep(0.005)
                continue

            if not ok or frame is None:
                consecutive_failures += 1
                if consecutive_failures in {1, 5, 20}:
                    self.logger.warning(
                        "Camera %s read failed (ok=%s) | consecutive_failures=%s",
                        slot.index,
                        ok,
                        consecutive_failures,
                    )
                await asyncio.sleep(0.01)
                continue
            consecutive_failures = 0

            queue.put_nowait(
                CapturedFrame(
                    frame=frame,
                    metadata=metadata or {},
                    timestamp=time.time(),
                    monotonic=time.perf_counter(),
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
        capture_index = getattr(slot, "capture_index", 0)
        capture_index += 1
        slot.capture_index = capture_index

        payload = FramePayload(
            frame=captured.frame,
            timestamp=timestamp,
            monotonic=monotonic,
            metadata=metadata,
            pixel_format="RGB888",
            stream="main",
            capture_index=capture_index,
            hardware_frame_number=None,
            dropped_since_last=None,
            sensor_timestamp_ns=None,
        )

        self._maybe_publish_preview(slot, payload)
        self._maybe_publish_storage(slot, payload, saving_allowed)

        if not slot.first_frame_event.is_set():
            slot.first_frame_event.set()

    def _maybe_publish_preview(self, slot: Any, payload: FramePayload) -> None:
        queue: Optional[asyncio.Queue] = getattr(slot, "preview_queue", None)
        if queue is None:
            return

        now = payload.monotonic
        stride_ok = payload.capture_index % max(1, getattr(slot, "preview_stride", 1)) == getattr(
            slot, "preview_stride_offset", 0
        )
        if not stride_ok:
            return
        if not slot.preview_gate.should_emit(now):
            return

        if queue.full():
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.logger.debug("Preview queue full for camera %s; frame dropped", slot.index)
            return

    def _maybe_publish_storage(
        self,
        slot: Any,
        payload: FramePayload,
        saving_allowed: bool,
    ) -> None:
        if not saving_allowed:
            return
        queue: Optional[asyncio.Queue] = getattr(slot, "storage_queue", None)
        if queue is None:
            return
        now = payload.monotonic
        if not slot.frame_rate_gate.should_emit(now):
            return
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            slot.storage_drop_since_last += 1
            slot.storage_drop_total += 1
            if slot.storage_drop_since_last <= 3:  # avoid spamming
                self.logger.warning(
                    "Storage queue full for camera %s (dropped %s, total %s)",
                    slot.index,
                    slot.storage_drop_since_last,
                    slot.storage_drop_total,
                )


__all__ = ["USBCapturePipeline"]
