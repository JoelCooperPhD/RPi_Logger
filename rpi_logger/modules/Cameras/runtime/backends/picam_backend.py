"""Picamera2 backend wrapper."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - cv2 may be missing in some environments
    cv2 = None  # type: ignore

import numpy as np

try:
    from picamera2 import Picamera2  # type: ignore
except Exception:  # pragma: no cover - picamera2 may be missing on some platforms
    Picamera2 = None  # type: ignore

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CapabilityMode, CameraCapabilities
from rpi_logger.modules.Cameras.runtime.capabilities import build_capabilities


@dataclass(slots=True)
class PicamFrame:
    data: np.ndarray
    timestamp: float  # monotonic seconds
    frame_number: int
    monotonic_ns: int
    sensor_timestamp_ns: Optional[int]
    wall_time: float
    wait_ms: float = 0.0
    color_format: str = "bgr"
    storage_queue_drops: int = 0


class PicamHandle:
    """Async iterator over Picamera2 frames."""

    def __init__(self, picam: "Picamera2", mode: CapabilityMode, *, logger: LoggerLike = None) -> None:
        self._cam = picam
        self.mode = mode
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._frame_number = 0
        self._running = True
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="picam2"
        )
        self._queue: Optional[asyncio.Queue] = None
        self._producer_future: Optional[concurrent.futures.Future] = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=2)
        await self._loop.run_in_executor(self._executor, self._configure_and_start)
        # Kick off a dedicated producer loop in the same executor to avoid per-frame scheduling overhead.
        self._producer_future = self._executor.submit(self._producer_loop)

    def _configure_and_start(self) -> None:
        config = self._cam.create_video_configuration(
            main={"size": self.mode.size, "format": "RGB888"},
            buffer_count=4,
        )
        controls = {**(config.get("controls") or {}), **(self.mode.controls or {})}
        target_fps = self.mode.fps if hasattr(self.mode, 'fps') and self.mode.fps else 30.0
        frame_duration_us = int(1_000_000 / target_fps)
        controls["FrameDurationLimits"] = (frame_duration_us, frame_duration_us)
        config["controls"] = controls
        self._cam.configure(config)
        self._cam.start()

    async def frames(self) -> AsyncIterator[PicamFrame]:
        first_logged = False
        queue = self._queue
        if queue is None:
            queue = asyncio.Queue()
            self._queue = queue
        try:
            while self._running:
                frame, metadata, capture_wait_ms = await queue.get()
                if frame is None:
                    break
                self._frame_number += 1
                monotonic_ns = time.monotonic_ns()
                sensor_ts_ns = _extract_sensor_timestamp(metadata)
                capture_ts_ns = sensor_ts_ns or monotonic_ns
                wall_ts = time.time()
                if not first_logged:
                    self._logger.info("Picam frame stream started (%s)", self.mode.size)
                    first_logged = True
                yield PicamFrame(
                    data=frame,
                    timestamp=capture_ts_ns / 1_000_000_000,
                    frame_number=self._frame_number,
                    monotonic_ns=monotonic_ns,
                    sensor_timestamp_ns=sensor_ts_ns,
                    wall_time=wall_ts,
                    wait_ms=capture_wait_ms,
                    color_format="rgb",  # Picamera2 RGB888 yields RGB order
                )
        except asyncio.CancelledError:
            self._logger.debug("Picam frames cancelled")
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        loop = self._loop or asyncio.get_running_loop()
        if self._queue:
            try:
                loop.call_soon_threadsafe(self._offer_frame, None, None, 0.0, True)
            except Exception:
                pass
        try:
            await loop.run_in_executor(self._executor, self._cam.stop)
        except Exception:  # pragma: no cover - defensive
            self._logger.debug("Picamera2 stop failed", exc_info=True)
        try:
            await loop.run_in_executor(self._executor, self._cam.close)
        except Exception:
            self._logger.debug("Picamera2 close failed", exc_info=True)
        self._shutdown_executor()

    def _producer_loop(self) -> None:
        """Continuously capture frames and hand off to the asyncio loop."""

        while self._running:
            frame, metadata, capture_wait_ms = self._capture_frame()
            if frame is None:
                continue
            loop = self._loop
            if not loop:
                continue
            try:
                loop.call_soon_threadsafe(self._offer_frame, frame, metadata, capture_wait_ms, False)
            except Exception:
                pass
        loop = self._loop
        if loop:
            try:
                loop.call_soon_threadsafe(self._offer_frame, None, None, 0.0, True)
            except Exception:
                pass

    def _offer_frame(self, frame, metadata, wait_ms: float, sentinel: bool = False) -> None:
        """Enqueue frame for the async consumer, dropping the oldest if full."""

        queue = self._queue
        if not queue:
            return
        if sentinel:
            try:
                queue.put_nowait((None, None, 0.0))
            except Exception:
                pass
            return
        if queue.full():
            try:
                queue.get_nowait()
            except Exception:
                pass
        try:
            queue.put_nowait((frame, metadata, wait_ms))
        except Exception:
            pass

    def _capture_frame(self):
        wait_start = time.perf_counter()
        request = self._cam.capture_request()
        capture_wait_ms = (time.perf_counter() - wait_start) * 1000.0
        if request is None:
            return None, None, capture_wait_ms
        metadata = {}
        frame = None
        try:
            with contextlib.suppress(Exception):
                metadata = request.get_metadata() or {}
            frame = request.make_array("main")
        except Exception:
            self._logger.debug("Picam capture_request failed", exc_info=True)
        finally:
            try:
                request.release()
            except Exception:
                pass
        return frame, metadata, capture_wait_ms

    def _shutdown_executor(self) -> None:
        if self._executor:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass
            self._executor = None


async def probe(sensor_id: str, *, logger: LoggerLike = None) -> Optional[CameraCapabilities]:
    log = ensure_structured_logger(logger, fallback_name=__name__)
    if Picamera2 is None:
        log.warning("Picamera2 not available; cannot probe sensor %s", sensor_id)
        return None
    return await asyncio.to_thread(_probe_sync, sensor_id, log)


def _probe_sync(sensor_id: str, log) -> Optional[CameraCapabilities]:
    try:
        cam = Picamera2(camera_num=int(sensor_id) if sensor_id.isdigit() else 0)
    except Exception as exc:
        log.warning("Failed to open Picamera2 sensor %s: %s", sensor_id, exc)
        return None

    modes = []
    try:
        for cfg in cam.sensor_modes or []:
            size = cfg.get("size") or (cfg.get("width"), cfg.get("height"))
            fps = cfg.get("fps", cfg.get("framerate", 30))
            modes.append({"size": size, "fps": fps, "pixel_format": "RGB"})
    finally:
        cam.close()

    return build_capabilities(modes)


async def open_device(sensor_id: str, mode: CapabilityMode, *, logger: LoggerLike = None) -> Optional[PicamHandle]:
    log = ensure_structured_logger(logger, fallback_name=__name__)
    if Picamera2 is None:
        log.warning("Picamera2 not available; cannot open sensor %s", sensor_id)
        return None
    # Guard against already-open handles on refresh by explicitly closing first.
    try:
        Picamera2.close_camera(int(sensor_id) if str(sensor_id).isdigit() else 0)
    except Exception:
        pass
    try:
        cam = Picamera2(camera_num=int(sensor_id) if sensor_id.isdigit() else 0)
    except Exception as exc:
        log.warning("Failed to open Picamera2 sensor %s: %s", sensor_id, exc)
        return None

    handle = PicamHandle(cam, mode, logger=logger)
    await handle.start()
    return handle


def supports_shared_streams(capabilities: CameraCapabilities, preview_mode: CapabilityMode, record_mode: CapabilityMode) -> bool:
    """Placeholder heuristic: assume shared streams when resolutions match."""

    return preview_mode.size == record_mode.size and preview_mode.pixel_format == record_mode.pixel_format


def _extract_sensor_timestamp(metadata: dict) -> Optional[int]:
    if not isinstance(metadata, dict):
        return None
    sensor_ts = metadata.get("SensorTimestamp")
    if isinstance(sensor_ts, (int, float)):
        try:
            return int(sensor_ts)
        except Exception:
            return None
    return None


def _to_bgr(frame: np.ndarray) -> np.ndarray:
    """Ensure frames are in BGR order for downstream OpenCV consumers."""

    if frame is None:
        return frame
    if frame.ndim == 3 and frame.shape[2] >= 3:
        if cv2 is not None:
            try:
                return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            except Exception:
                pass
        # Fallback channel swap if cv2 is unavailable
        return frame[..., :3][..., ::-1]
    return frame


__all__ = ["PicamHandle", "PicamFrame", "probe", "open_device", "supports_shared_streams"]
