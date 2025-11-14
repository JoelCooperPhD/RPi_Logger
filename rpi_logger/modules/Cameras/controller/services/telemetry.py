"""Sensor/telemetry helpers for the Cameras controller."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from ...domain.model import FramePayload
from ...io.storage import StorageWriteResult
from ...logging_utils import get_module_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..slot import CameraSlot
    from ..runtime import CameraController


logger = get_module_logger(__name__)


class TelemetryService:
    """Handles frame cadence, telemetry, and storage health."""

    def __init__(self, controller: "CameraController") -> None:
        self._controller = controller
        self._sensor_sync_pending = False
        self._logger = controller.logger.getChild("telemetry")

    # ------------------------------------------------------------------
    # Sensor cadence helpers

    async def apply_frame_rate(self, slot: "CameraSlot") -> None:
        camera = slot.camera
        if not camera:
            return

        target_interval = self.current_sensor_interval()
        controller = self._controller

        if target_interval is None:
            if slot.frame_duration_us is not None:
                default_us = max(3333, int(1_000_000 / controller.MAX_SENSOR_FPS))
                try:
                    await asyncio.to_thread(
                        camera.set_controls,
                        {"FrameDurationLimits": (default_us, default_us)},
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self._logger.debug("FrameDuration reset failed for cam %s: %s", slot.index, exc)
                slot.frame_duration_us = None
            return

        frame_us = max(3333, int(target_interval * 1_000_000))
        if slot.frame_duration_us == frame_us:
            return

        try:
            await asyncio.to_thread(
                camera.set_controls,
                {"FrameDurationLimits": (frame_us, frame_us)},
            )
            slot.frame_duration_us = frame_us
            self._logger.info(
                "Camera %s sensor frame duration set to %.2f ms",
                slot.index,
                frame_us / 1000.0,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.debug("Unable to set frame duration for cam %s: %s", slot.index, exc)

    def current_sensor_interval(self) -> Optional[float]:
        controller = self._controller
        interval = controller.save_frame_interval
        if interval and interval > 0:
            return interval
        return None

    async def sync_sensor_frame_rates(self) -> None:
        controller = self._controller
        for slot in controller._previews:
            try:
                await self.apply_frame_rate(slot)
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.debug("Frame rate sync failed for cam %s: %s", slot.index, exc)

    async def flush_sensor_sync(self) -> None:
        if not self._sensor_sync_pending:
            return
        self._sensor_sync_pending = False
        await self.sync_sensor_frame_rates()

    def request_sensor_sync(self) -> None:
        controller = self._controller
        if controller._stop_event.is_set():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self._sensor_sync_pending = True
            return
        controller.task_manager.create(
            self.sync_sensor_frame_rates(),
            name="CameraSensorSync",
        )
        self._sensor_sync_pending = False

    # ------------------------------------------------------------------
    # FPS helpers

    def probe_slot_fps(self, slot: "CameraSlot") -> float:
        controller = self._controller
        for candidate in (
            getattr(slot, "last_observed_fps", 0.0),
            getattr(slot, "last_hardware_fps", 0.0),
        ):
            if candidate and candidate > 0:
                return min(float(candidate), controller.MAX_SENSOR_FPS)
        interval_ns = getattr(slot, "last_expected_interval_ns", None)
        if interval_ns and interval_ns > 0:
            fps = 1_000_000_000.0 / float(interval_ns)
            if fps > 0:
                return min(fps, controller.MAX_SENSOR_FPS)
        return 0.0

    async def await_slot_fps(self, slot: "CameraSlot", timeout: float = 1.0) -> float:
        fps = self.probe_slot_fps(slot)
        if fps > 0:
            return fps
        deadline = time.monotonic() + max(0.05, timeout)
        while time.monotonic() < deadline:
            await asyncio.sleep(0.02)
            fps = self.probe_slot_fps(slot)
            if fps > 0:
                return fps
        return 0.0

    def resolve_video_fps(self, slot: "CameraSlot") -> float:
        controller = self._controller
        fps = self.probe_slot_fps(slot)
        if fps > 0:
            return fps
        if controller.save_frame_interval > 0:
            fps = 1.0 / controller.save_frame_interval
            return min(max(fps, 1.0), controller.MAX_SENSOR_FPS)
        return 30.0

    # ------------------------------------------------------------------
    # Telemetry / queue health

    def log_capture_failure(self, slot: "CameraSlot", elapsed: float, exc: Exception) -> None:
        controller = self._controller
        slot.slow_capture_warnings += 1
        if slot.slow_capture_warnings <= 5 or slot.slow_capture_warnings % 25 == 0:
            self._logger.warning(
                "Capture loop error (camera %s) after %.3fs (saving=%s, queue=%s): %s",
                slot.index,
                elapsed,
                controller.save_enabled,
                slot.storage_queue_size,
                exc,
            )

    def record_capture_latency(self, slot: "CameraSlot", elapsed: float) -> None:
        controller = self._controller
        if elapsed > controller.CAPTURE_SLOW_REQUEST_THRESHOLD:
            slot.slow_capture_warnings += 1
            if slot.slow_capture_warnings <= 5 or slot.slow_capture_warnings % 25 == 0:
                session_name = controller.session_dir.name if controller.session_dir else "n/a"
                self._logger.warning(
                    "Camera %s capture_request slow: %.3fs (saving=%s, session=%s)",
                    slot.index,
                    elapsed,
                    controller.save_enabled,
                    session_name,
                )
        elif slot.slow_capture_warnings and elapsed < controller.CAPTURE_SLOW_REQUEST_THRESHOLD / 2:
            slot.slow_capture_warnings = 0

    def _update_storage_metrics(self, slot: "CameraSlot", result: StorageWriteResult) -> bool:
        pipeline = slot.storage_pipeline
        if pipeline is not None:
            slot.last_video_frame_count = pipeline.video_frame_count
        slot.last_video_fps = result.video_fps
        if result.video_written:
            slot.video_stall_frames = 0
            return False
        slot.video_stall_frames += 1
        controller = self._controller
        return slot.video_stall_frames >= controller.VIDEO_STALL_THRESHOLD

    def _emit_frame_telemetry(
        self,
        slot: "CameraSlot",
        payload: FramePayload,
        *,
        image_path: Optional[Path],
        video_written: bool,
        queue_drops: int = 0,
        video_fps: float = 0.0,
    ) -> None:
        sensor_ts = payload.sensor_timestamp_ns
        sensor_part = f"sensor={sensor_ts}ns" if sensor_ts is not None else f"ts={payload.timestamp:.3f}s"
        drops = payload.dropped_since_last
        drop_part = f"drops={drops}" if drops is not None else "drops=0"
        video_part = "video=Y" if video_written else "video=N"
        image_part = f"img={image_path.name}" if image_path is not None else ""

        components = [
            f"Cam{slot.index} frame {payload.capture_index}",
            sensor_part,
            drop_part,
            video_part,
        ]
        if image_part:
            components.append(image_part)
        if queue_drops:
            components.append(f"qdrop={queue_drops}")
        if video_fps > 0:
            components.append(f"fps={video_fps:.2f}")

        entry = " | ".join(components)
        self._logger.debug("Storage telemetry -> %s", entry)

    async def on_storage_result(
        self,
        slot: "CameraSlot",
        payload: FramePayload,
        storage_result: StorageWriteResult,
        queue_drops: int,
    ) -> bool:
        controller = self._controller
        image_path = storage_result.image_path
        if image_path is not None:
            controller._saved_count += 1
            if controller._saved_count <= 3 or controller._saved_count % 25 == 0:
                self._logger.info(
                    "Camera %s stored still %d -> %s (total saved %d)",
                    slot.index,
                    payload.capture_index,
                    image_path,
                    controller._saved_count,
                )

        pipeline = slot.storage_pipeline
        if pipeline is not None:
            pipeline.log_frame(payload, queue_drops=queue_drops)

        self._emit_frame_telemetry(
            slot,
            payload,
            image_path=image_path,
            video_written=storage_result.video_written,
            queue_drops=queue_drops,
            video_fps=storage_result.video_fps,
        )

        stalled = self._update_storage_metrics(slot, storage_result)
        if stalled:
            await self.handle_storage_failure(slot, "video writer stalled")
            return False
        return True

    async def handle_storage_failure(self, slot: "CameraSlot", reason: str) -> None:
        controller = self._controller
        if controller._storage_failure_reported:
            return
        controller._storage_failure_reported = True
        self._logger.error(
            "Storage failure on camera %s: %s (video_frames=%d, queue_drops=%d)",
            slot.index,
            reason,
            slot.last_video_frame_count,
            slot.storage_drop_total,
        )
        controller.view_manager.set_status(f"Recording stopped: {reason}", level=logging.ERROR)
        await controller.storage_manager.disable_saving()
        await controller.setup_manager.reinitialize_cameras()


__all__ = ["TelemetryService"]
