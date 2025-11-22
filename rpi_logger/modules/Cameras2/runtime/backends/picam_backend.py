"""Picamera2 backend wrapper."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import numpy as np

try:
    from picamera2 import Picamera2  # type: ignore
except Exception:  # pragma: no cover - picamera2 may be missing on some platforms
    Picamera2 = None  # type: ignore

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras2.runtime import CapabilityMode, CameraCapabilities
from rpi_logger.modules.Cameras2.runtime.discovery.capabilities import build_capabilities


@dataclass(slots=True)
class PicamFrame:
    data: np.ndarray
    timestamp: float
    frame_number: int
    wait_ms: float = 0.0


class PicamHandle:
    """Async iterator over Picamera2 frames."""

    def __init__(self, picam: "Picamera2", mode: CapabilityMode, *, logger: LoggerLike = None) -> None:
        self._cam = picam
        self.mode = mode
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._frame_number = 0
        self._running = True

    async def start(self) -> None:
        await asyncio.to_thread(self._configure_and_start)

    def _configure_and_start(self) -> None:
        # Force a 3-channel RGB preview buffer to avoid channel-order surprises (e.g., XBGR).
        self._cam.configure(self._cam.create_preview_configuration(main={"size": self.mode.size, "format": "RGB888"}))
        self._cam.start()

    async def frames(self) -> AsyncIterator[PicamFrame]:
        try:
            while self._running:
                wait_start = time.perf_counter()
                frame = await asyncio.to_thread(self._cam.capture_array, "main")
                wait_ms = (time.perf_counter() - wait_start) * 1000.0
                self._frame_number += 1
                ts = time.time()
                yield PicamFrame(data=frame, timestamp=ts, frame_number=self._frame_number, wait_ms=wait_ms)
        except asyncio.CancelledError:
            self._logger.debug("Picam frames cancelled")
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            await asyncio.to_thread(self._cam.stop)
        except Exception:  # pragma: no cover - defensive
            self._logger.debug("Picamera2 stop failed", exc_info=True)
        try:
            await asyncio.to_thread(self._cam.close)
        except Exception:
            self._logger.debug("Picamera2 close failed", exc_info=True)


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


__all__ = ["PicamHandle", "PicamFrame", "probe", "open_device", "supports_shared_streams"]
