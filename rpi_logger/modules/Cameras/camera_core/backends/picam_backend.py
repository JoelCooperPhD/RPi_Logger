"""Picamera2 backend wrapper."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

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
from rpi_logger.modules.Cameras.camera_core.state import CapabilityMode, CameraCapabilities, ControlInfo, ControlType
from rpi_logger.modules.Cameras.camera_core.capabilities import build_capabilities


# Known Picamera2 enum controls and their options
PICAM_ENUMS: Dict[str, List[str]] = {
    "AwbMode": ["Off", "Auto", "Incandescent", "Tungsten", "Fluorescent",
                "Indoor", "Daylight", "Cloudy", "Custom"],
    "AeExposureMode": ["Normal", "Short", "Long", "Custom"],
    "AeMeteringMode": ["CentreWeighted", "Spot", "Average", "Custom"],
    "NoiseReductionMode": ["Off", "Fast", "HighQuality", "Minimal", "ZSL"],
    "AfMode": ["Manual", "Auto", "Continuous"],
    "AfRange": ["Normal", "Macro", "Full"],
    "AfSpeed": ["Normal", "Fast"],
}


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

    def set_control(self, name: str, value: Any) -> bool:
        """Set a camera control value. Returns True on success."""
        if not self._cam:
            self._logger.warning("Cannot set control %s: camera not open", name)
            return False

        try:
            # Handle enum controls - convert string to index if needed
            if name in PICAM_ENUMS and isinstance(value, str):
                options = PICAM_ENUMS[name]
                if value in options:
                    value = options.index(value)
                else:
                    self._logger.warning("Invalid enum value %s for %s", value, name)
                    return False

            # Apply control via set_controls
            self._cam.set_controls({name: value})
            self._logger.debug("Set control %s = %s via Picamera2", name, value)
            return True
        except Exception as e:
            self._logger.warning("Failed to set control %s: %s", name, e)
            return False


# ---------------------------------------------------------------------------
# Control probing functions


def _probe_controls_picam(cam: "Picamera2", log) -> Dict[str, ControlInfo]:
    """Extract controls from Picamera2.camera_controls."""
    controls: Dict[str, ControlInfo] = {}

    try:
        cam_controls = getattr(cam, "camera_controls", None) or {}
    except Exception as e:
        log.debug("Failed to get camera_controls: %s", e)
        return controls

    for name, info in cam_controls.items():
        try:
            # info is typically (min, max, default) tuple
            min_val: Any = None
            max_val: Any = None
            default_val: Any = None

            if isinstance(info, tuple):
                if len(info) >= 1:
                    min_val = info[0]
                if len(info) >= 2:
                    max_val = info[1]
                if len(info) >= 3:
                    default_val = info[2]
            else:
                default_val = info

            # Determine control type
            if name in PICAM_ENUMS:
                control_type = ControlType.ENUM
                options = PICAM_ENUMS[name]
            elif name.endswith("Limits"):
                # e.g., FrameDurationLimits, ExposureTimeLimits
                control_type = ControlType.TUPLE
                options = None
            elif isinstance(default_val, bool):
                control_type = ControlType.BOOLEAN
                options = None
            elif isinstance(default_val, float) and not isinstance(default_val, bool):
                control_type = ControlType.FLOAT
                options = None
            elif isinstance(default_val, int):
                control_type = ControlType.INTEGER
                options = None
            else:
                control_type = ControlType.UNKNOWN
                options = None

            controls[name] = ControlInfo(
                name=name,
                control_type=control_type,
                current_value=default_val,  # Use default as "current" at probe time
                min_value=min_val,
                max_value=max_val,
                default_value=default_val,
                options=options,
                read_only=False,
                backend_id=name,  # Picam uses string keys
            )
            log.debug(
                "Picam control %s: type=%s min=%s max=%s default=%s",
                name, control_type.value, min_val, max_val, default_val,
            )
        except Exception as e:
            log.debug("Failed to parse control %s: %s", name, e)
            continue

    return controls


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

    modes: List[Dict[str, Any]] = []
    controls: Dict[str, ControlInfo] = {}
    global_limits: Dict[str, Any] = {}

    try:
        # Extract sensor modes with additional metadata
        for cfg in cam.sensor_modes or []:
            size = cfg.get("size") or (cfg.get("width"), cfg.get("height"))
            fps = cfg.get("fps", cfg.get("framerate", 30))

            # Extract per-mode metadata
            mode_controls: Dict[str, Any] = {}

            # Exposure limits
            if "exposure_limits" in cfg:
                exp_limits = cfg["exposure_limits"]
                mode_controls["ExposureLimits"] = exp_limits
                # Merge into global limits (take widest range)
                if exp_limits[0] is not None:
                    if "exposure_min" not in global_limits or exp_limits[0] < global_limits["exposure_min"]:
                        global_limits["exposure_min"] = exp_limits[0]
                if exp_limits[1] is not None:
                    if "exposure_max" not in global_limits or exp_limits[1] > global_limits.get("exposure_max", 0):
                        global_limits["exposure_max"] = exp_limits[1]

            # Crop limits
            if "crop_limits" in cfg:
                mode_controls["CropLimits"] = cfg["crop_limits"]

            # Bit depth
            if "bit_depth" in cfg:
                mode_controls["BitDepth"] = cfg["bit_depth"]

            # Native format
            if "format" in cfg:
                mode_controls["NativeFormat"] = str(cfg["format"])

            modes.append({
                "size": size,
                "fps": fps,
                "pixel_format": "RGB",
                "controls": mode_controls,
            })
            log.debug(
                "Picam mode %s @ %.1f fps, exposure_limits=%s, crop_limits=%s",
                size, fps, cfg.get("exposure_limits"), cfg.get("crop_limits"),
            )

        # Probe camera-level controls
        controls = _probe_controls_picam(cam, log)
        if controls:
            log.info("Probed %d controls from Picamera2 for sensor %s", len(controls), sensor_id)

    finally:
        cam.close()

    # Build capabilities and attach controls/limits
    caps = build_capabilities(modes)
    caps.controls = controls
    caps.limits = global_limits
    return caps


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


__all__ = ["PicamHandle", "PicamFrame", "probe", "open_device", "supports_shared_streams"]
