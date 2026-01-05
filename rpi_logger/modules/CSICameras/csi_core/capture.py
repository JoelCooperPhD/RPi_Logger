"""
CSI camera capture implementation using Picamera2.

This module provides PicamCapture for Raspberry Pi CSI cameras.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Optional, Tuple

import numpy as np

from rpi_logger.modules.base.camera_types import CaptureFrame, CaptureHandle
from rpi_logger.modules.CSICameras.csi_core.backends.picam_color import get_picam_color_format
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)

# Try to import Picamera2 - may not be available on non-Pi platforms
try:
    from picamera2 import Picamera2  # type: ignore
except Exception:  # pragma: no cover - picamera2 may be absent on non-Pi platforms
    Picamera2 = None  # type: ignore


class PicamCapture(CaptureHandle):
    """Picamera2-based capture for Raspberry Pi cameras."""

    def __init__(
        self,
        sensor_id: str,
        resolution: tuple[int, int],
        fps: float,
        lores_size: Optional[Tuple[int, int]] = None,
    ) -> None:
        if Picamera2 is None:
            raise RuntimeError(
                "Picamera2 is not available. "
                "Install with: pip install picamera2"
            )
        self._sensor_id = sensor_id
        self._resolution = resolution
        self._fps = fps
        self._lores_size = lores_size  # If set, enables dual-stream with ISP-scaled lores
        self._cam = None
        self._running = False
        self._frame_number = 0

    @property
    def actual_fps(self) -> float:
        """Return the actual FPS - for Picam this equals requested since it's hardware-enforced."""
        return self._fps

    async def start(self) -> None:
        cam_num = int(self._sensor_id) if self._sensor_id.isdigit() else 0
        logger.info("Opening Picamera2 sensor %s (cam_num=%d)", self._sensor_id, cam_num)

        # Run all blocking Picamera2 operations in thread pool
        await asyncio.to_thread(self._start_sync, cam_num)
        self._running = True

    def _start_sync(self, cam_num: int) -> None:
        try:
            Picamera2.close_camera(cam_num)
        except Exception:
            pass

        logger.info("Creating Picamera2 instance...")
        self._cam = Picamera2(camera_num=cam_num)
        logger.info("Creating video configuration: %s @ %.1f fps", self._resolution, self._fps)

        config = self._cam.create_video_configuration(
            main={"size": self._resolution, "format": "RGB888"},
            buffer_count=4,
        )

        # Add lores stream if requested (for efficient ISP-scaled preview)
        if self._lores_size is not None:
            # Lores must use YUV420 format (hardware limitation on Pi 4 and earlier)
            # Pi 5 can use RGB for lores, but YUV420 is more efficient
            config["lores"] = {
                "size": self._lores_size,
                "format": "YUV420",
            }
            logger.info("Enabling lores stream: %s (YUV420)", self._lores_size)

        controls = config.get("controls") or {}
        frame_duration_us = int(1_000_000 / self._fps)
        controls["FrameDurationLimits"] = (frame_duration_us, frame_duration_us)
        config["controls"] = controls

        logger.info("Configuring camera...")
        self._cam.configure(config)
        logger.info("Starting camera...")
        self._cam.start()
        logger.info("Camera started successfully")

    async def frames(self) -> AsyncIterator[CaptureFrame]:
        import contextlib

        while self._running:
            request = await asyncio.to_thread(self._cam.capture_request)
            if request is None:
                continue

            self._frame_number += 1
            monotonic_ns = time.monotonic_ns()
            wall_time = time.time()

            metadata = {}
            frame = None
            lores_frame = None
            try:
                with contextlib.suppress(Exception):
                    metadata = request.get_metadata() or {}
                frame = request.make_array("main")

                # Capture lores frame if configured
                if self._lores_size is not None:
                    try:
                        lores_frame = request.make_array("lores")
                    except Exception:
                        # Lores may not be available (e.g., config failed)
                        pass
            finally:
                try:
                    request.release()
                except Exception:
                    pass

            if frame is None:
                continue

            sensor_ts = self._extract_sensor_timestamp(metadata)

            # Color format from picam_color module - see that file for IMX296 bug explanation
            yield CaptureFrame(
                data=frame,
                timestamp=monotonic_ns / 1_000_000_000,
                frame_number=self._frame_number,
                monotonic_ns=monotonic_ns,
                sensor_timestamp_ns=sensor_ts,
                wall_time=wall_time,
                color_format=get_picam_color_format(),
                lores_data=lores_frame,
                lores_format="yuv420" if lores_frame is not None else "",
            )

    async def stop(self) -> None:
        self._running = False
        if self._cam:
            try:
                await asyncio.to_thread(self._cam.stop)
            except Exception:
                pass
            try:
                await asyncio.to_thread(self._cam.close)
            except Exception:
                pass
            self._cam = None

    @staticmethod
    def _extract_sensor_timestamp(metadata: dict) -> Optional[int]:
        sensor_ts = metadata.get("SensorTimestamp")
        if isinstance(sensor_ts, (int, float)):
            try:
                return int(sensor_ts)
            except Exception:
                return None
        return None

    def set_control(self, name: str, value: Any) -> bool:
        """Set a Picamera2 control value."""
        if not self._cam:
            logger.warning("Cannot set control %s: camera not open", name)
            return False

        try:
            # Handle enum controls - convert string to index if needed
            from rpi_logger.modules.CSICameras.csi_core.backends.picam_backend import PICAM_ENUMS
            if name in PICAM_ENUMS and isinstance(value, str):
                options = PICAM_ENUMS[name]
                if value in options:
                    value = options.index(value)
                else:
                    logger.warning("Invalid enum value %s for %s", value, name)
                    return False

            self._cam.set_controls({name: value})
            logger.debug("Set Picam control %s = %s", name, value)
            return True
        except Exception as e:
            logger.warning("Failed to set Picam control %s: %s", name, e)
            return False


__all__ = ["PicamCapture"]
