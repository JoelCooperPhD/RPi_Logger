"""
Camera capture abstraction.

Provides a unified interface for Picamera2 and USB cameras.
Runs directly in-process (no subprocess).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Tuple

import numpy as np

from rpi_logger.modules.Cameras.config import DEFAULT_CAPTURE_RESOLUTION, DEFAULT_CAPTURE_FPS
from rpi_logger.modules.Cameras.camera_core.backends.picam_color import get_picam_color_format

# Try to import Picamera2 - may not be available on non-Pi platforms
try:
    from picamera2 import Picamera2  # type: ignore
except Exception:  # pragma: no cover - picamera2 may be absent on non-Pi platforms
    Picamera2 = None  # type: ignore


@dataclass(slots=True)
class CaptureFrame:
    """Unified frame data from any camera backend."""
    data: np.ndarray
    timestamp: float  # monotonic seconds
    frame_number: int
    monotonic_ns: int
    sensor_timestamp_ns: Optional[int]
    wall_time: float
    color_format: str = "bgr"
    # Lores (low resolution) frame from ISP (Picamera2 only)
    # Used for efficient preview without CPU resize
    lores_data: Optional[np.ndarray] = None
    lores_format: str = ""  # "yuv420" when lores is available


class CaptureHandle:
    """Abstract base for camera capture."""

    async def start(self) -> None:
        raise NotImplementedError

    async def frames(self) -> AsyncIterator[CaptureFrame]:
        raise NotImplementedError
        yield  # type: ignore

    async def stop(self) -> None:
        raise NotImplementedError

    def set_control(self, name: str, value: Any) -> bool:
        """Set a camera control value. Returns True on success."""
        return False


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
        import logging
        log = logging.getLogger(__name__)

        cam_num = int(self._sensor_id) if self._sensor_id.isdigit() else 0
        log.info("Opening Picamera2 sensor %s (cam_num=%d)", self._sensor_id, cam_num)

        # Run all blocking Picamera2 operations in thread pool
        await asyncio.to_thread(self._start_sync, cam_num, log)
        self._running = True

    def _start_sync(self, cam_num: int, log) -> None:
        try:
            Picamera2.close_camera(cam_num)
        except Exception:
            pass

        log.info("Creating Picamera2 instance...")
        self._cam = Picamera2(camera_num=cam_num)
        log.info("Creating video configuration: %s @ %.1f fps", self._resolution, self._fps)

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
            log.info("Enabling lores stream: %s (YUV420)", self._lores_size)

        controls = config.get("controls") or {}
        frame_duration_us = int(1_000_000 / self._fps)
        controls["FrameDurationLimits"] = (frame_duration_us, frame_duration_us)
        config["controls"] = controls

        log.info("Configuring camera...")
        self._cam.configure(config)
        log.info("Starting camera...")
        self._cam.start()
        log.info("Camera started successfully")

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
        import logging
        log = logging.getLogger(__name__)

        if not self._cam:
            log.warning("Cannot set control %s: camera not open", name)
            return False

        try:
            # Handle enum controls - convert string to index if needed
            from rpi_logger.modules.Cameras.camera_core.backends.picam_backend import PICAM_ENUMS
            if name in PICAM_ENUMS and isinstance(value, str):
                options = PICAM_ENUMS[name]
                if value in options:
                    value = options.index(value)
                else:
                    log.warning("Invalid enum value %s for %s", value, name)
                    return False

            self._cam.set_controls({name: value})
            log.debug("Set Picam control %s = %s", name, value)
            return True
        except Exception as e:
            log.warning("Failed to set Picam control %s: %s", name, e)
            return False


class USBCapture(CaptureHandle):
    """OpenCV-based capture for USB cameras."""

    def __init__(self, dev_path: str, resolution: tuple[int, int], fps: float) -> None:
        self._dev_path = dev_path
        self._resolution = resolution
        self._requested_fps = fps
        self._actual_fps = fps  # Updated after camera opens to reflect what camera reports
        self._cap = None
        self._running = False
        self._frame_number = 0

    @property
    def actual_fps(self) -> float:
        """Return the actual FPS the camera is configured to deliver."""
        return self._actual_fps

    async def start(self) -> None:
        import logging
        import sys
        import cv2

        log = logging.getLogger(__name__)
        device_id = int(self._dev_path) if self._dev_path.isdigit() else self._dev_path
        log.info("Opening USB camera: %s", device_id)

        # Prefer V4L2 on Linux
        backend = getattr(cv2, "CAP_V4L2", None) if sys.platform == "linux" else None
        if backend is not None:
            self._cap = cv2.VideoCapture(device_id, backend)
        else:
            self._cap = cv2.VideoCapture(device_id)

        if not self._cap or not self._cap.isOpened():
            raise RuntimeError(f"Failed to open USB camera: {self._dev_path}")

        # Configure MJPEG format and resolution
        try:
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self._cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])
        self._cap.set(cv2.CAP_PROP_FPS, self._requested_fps)

        # Disable dynamic framerate (some cameras lower FPS in low light otherwise)
        # This is controlled via v4l2-ctl as OpenCV doesn't expose this property
        if sys.platform == "linux" and isinstance(device_id, str) and device_id.startswith("/dev/video"):
            import subprocess
            try:
                subprocess.run(
                    ["v4l2-ctl", "-d", device_id, "-c", "exposure_dynamic_framerate=0"],
                    capture_output=True, timeout=2.0
                )
                log.debug("Disabled exposure_dynamic_framerate for %s", device_id)
            except Exception as e:
                log.debug("Could not set exposure_dynamic_framerate: %s", e)

        # Read a test frame to verify the camera works (with retry for cameras that need warmup)
        import time as _time
        for attempt in range(3):
            if attempt > 0:
                _time.sleep(0.2)
            success, _ = self._cap.read()
            if success:
                break
            log.debug("USB camera %s test frame attempt %d failed, retrying...", self._dev_path, attempt + 1)
        if not success:
            self._cap.release()
            raise RuntimeError(f"USB camera {self._dev_path} opened but cannot read frames")

        # Query the actual FPS the camera reports - this may differ from requested
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        reported_fps = self._cap.get(cv2.CAP_PROP_FPS)

        # Use reported FPS if valid, otherwise fall back to requested
        if reported_fps and reported_fps > 0:
            self._actual_fps = float(reported_fps)
        else:
            self._actual_fps = self._requested_fps

        if abs(self._actual_fps - self._requested_fps) > 0.5:
            log.warning("USB camera %s: requested %.1f fps but camera reports %.1f fps",
                       self._dev_path, self._requested_fps, self._actual_fps)

        log.info("USB camera opened successfully: %dx%d @ %.1f fps (requested %.1f)",
                actual_w, actual_h, self._actual_fps, self._requested_fps)
        self._running = True

    async def frames(self) -> AsyncIterator[CaptureFrame]:
        import queue
        frame_queue: queue.Queue = queue.Queue(maxsize=2)

        def capture_thread():
            consecutive_failures = 0
            while self._running:
                success, frame = self._cap.read()
                if not success:
                    consecutive_failures += 1
                    if consecutive_failures >= 10:
                        frame_queue.put(None)
                        return
                    continue
                consecutive_failures = 0
                self._frame_number += 1
                try:
                    frame_queue.put((frame, time.monotonic_ns(), time.time()), timeout=0.1)
                except queue.Full:
                    pass  # Drop frame if consumer is slow
            frame_queue.put(None)

        import threading
        thread = threading.Thread(target=capture_thread, daemon=True)
        thread.start()

        while self._running:
            try:
                item = await asyncio.to_thread(frame_queue.get, timeout=1.0)
            except Exception:
                continue
            if item is None:
                break
            frame, monotonic_ns, wall_time = item
            yield CaptureFrame(
                data=frame,
                timestamp=monotonic_ns / 1_000_000_000,
                frame_number=self._frame_number,
                monotonic_ns=monotonic_ns,
                sensor_timestamp_ns=None,
                wall_time=wall_time,
                color_format="bgr",
            )

    async def stop(self) -> None:
        self._running = False
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def set_control(self, name: str, value: Any) -> bool:
        """Set a USB camera control value via OpenCV or v4l2-ctl."""
        import logging
        import sys
        import subprocess

        log = logging.getLogger(__name__)

        if not self._cap or not self._cap.isOpened():
            log.warning("Cannot set control %s: camera not open", name)
            return False

        # Map of control names to OpenCV property IDs
        import cv2
        CV_CONTROL_PROPS = {
            "Brightness": cv2.CAP_PROP_BRIGHTNESS,
            "Contrast": cv2.CAP_PROP_CONTRAST,
            "Saturation": cv2.CAP_PROP_SATURATION,
            "Hue": cv2.CAP_PROP_HUE,
            "Gain": cv2.CAP_PROP_GAIN,
            "Gamma": cv2.CAP_PROP_GAMMA,
            "Exposure": cv2.CAP_PROP_EXPOSURE,
            "AutoExposure": cv2.CAP_PROP_AUTO_EXPOSURE,
            "WhiteBalanceBlueU": cv2.CAP_PROP_WHITE_BALANCE_BLUE_U,
            "WhiteBalanceRedV": cv2.CAP_PROP_WHITE_BALANCE_RED_V,
            "Focus": cv2.CAP_PROP_FOCUS,
            "AutoFocus": cv2.CAP_PROP_AUTOFOCUS,
            "Zoom": cv2.CAP_PROP_ZOOM,
            "Backlight": cv2.CAP_PROP_BACKLIGHT,
            "Pan": cv2.CAP_PROP_PAN,
            "Tilt": cv2.CAP_PROP_TILT,
        }

        # Controls that OpenCV reports success for but don't actually work
        # on many V4L2 cameras - skip OpenCV and use v4l2-ctl directly
        OPENCV_UNRELIABLE_CONTROLS = {"Gain", "AutoExposure", "Exposure"}

        cv_value = int(value) if isinstance(value, bool) else value

        # Try OpenCV first (for controls that work reliably)
        prop_id = CV_CONTROL_PROPS.get(name)
        if prop_id is not None and name not in OPENCV_UNRELIABLE_CONTROLS:
            try:
                old_value = self._cap.get(prop_id)
                result = self._cap.set(prop_id, cv_value)
                if result:
                    # Verify the value actually changed
                    new_value = self._cap.get(prop_id)
                    # Allow some tolerance for float comparisons
                    if abs(new_value - cv_value) < 1.0:
                        log.debug("Set USB control %s = %s via OpenCV (verified)", name, value)
                        return True
                    else:
                        log.debug("OpenCV set %s returned True but value unchanged (old=%s, new=%s, target=%s)",
                                 name, old_value, new_value, cv_value)
            except Exception as e:
                log.debug("OpenCV set error for %s: %s", name, e)

        # Use v4l2-ctl on Linux (primary method for unreliable controls, fallback for others)
        if sys.platform == "linux" and self._dev_path.startswith("/dev/video"):
            # Convert PascalCase to snake_case for v4l2
            v4l2_name = self._to_snake_case(name)
            try:
                result = subprocess.run(
                    ["v4l2-ctl", "-d", self._dev_path, f"--set-ctrl={v4l2_name}={int(cv_value)}"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
                if result.returncode == 0:
                    log.debug("Set USB control %s = %s via v4l2-ctl", name, value)
                    return True
                else:
                    log.debug("v4l2-ctl set failed for %s: %s", name, result.stderr.strip())
            except FileNotFoundError:
                log.debug("v4l2-ctl not found")
            except subprocess.TimeoutExpired:
                log.debug("v4l2-ctl timed out setting %s", name)
            except Exception as e:
                log.debug("v4l2-ctl error setting %s: %s", name, e)

        log.warning("Unable to set USB control %s", name)
        return False

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert PascalCase to snake_case for v4l2."""
        result = []
        for i, char in enumerate(name):
            if i > 0 and char.isupper():
                result.append("_")
            result.append(char.lower())
        return "".join(result)


async def open_capture(
    camera_type: str,
    camera_id: str,
    resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION,
    fps: float = DEFAULT_CAPTURE_FPS,
    lores_size: Optional[Tuple[int, int]] = None,
) -> Tuple[CaptureHandle, dict]:
    """
    Open a camera and return (capture_handle, capabilities).

    Args:
        camera_type: "picam" or "usb"
        camera_id: sensor ID or device path
        resolution: capture resolution (width, height)
        fps: target frame rate
        lores_size: optional low-resolution stream size for preview (Picamera2 only)

    Returns:
        Tuple of (CaptureHandle, capabilities dict)
    """
    if camera_type == "picam":
        capture = PicamCapture(camera_id, resolution, fps, lores_size=lores_size)
    elif camera_type == "usb":
        capture = USBCapture(camera_id, resolution, fps)
    else:
        raise ValueError(f"Unknown camera type: {camera_type}")

    await capture.start()

    # Return actual FPS after camera opened - may differ from requested for USB cameras
    capabilities: dict = {
        "camera_type": camera_type,
        "camera_id": camera_id,
        "resolution": resolution,
        "requested_fps": fps,
        "actual_fps": capture.actual_fps,
        "lores_size": lores_size if camera_type == "picam" and lores_size else None,
    }

    return capture, capabilities


__all__ = ["CaptureFrame", "CaptureHandle", "PicamCapture", "USBCapture", "open_capture"]
