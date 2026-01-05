"""
USB camera capture abstraction.

Provides capture interface for USB cameras via OpenCV/V4L2.
Runs directly in-process (no subprocess).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Tuple

import numpy as np

from rpi_logger.modules.Cameras.config import DEFAULT_CAPTURE_RESOLUTION, DEFAULT_CAPTURE_FPS
from rpi_logger.modules.Cameras.camera_core.utils import to_snake_case
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


@dataclass(slots=True)
class CaptureFrame:
    """Frame data from USB camera backend."""
    data: np.ndarray
    timestamp: float  # monotonic seconds
    frame_number: int
    monotonic_ns: int
    sensor_timestamp_ns: Optional[int]
    wall_time: float
    color_format: str = "bgr"
    # Lores fields kept for interface compatibility (always None for USB)
    lores_data: Optional[np.ndarray] = None
    lores_format: str = ""


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
        import sys
        import cv2

        device_id = int(self._dev_path) if self._dev_path.isdigit() else self._dev_path
        logger.info("Opening USB camera: %s", device_id)

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
                logger.debug("Disabled exposure_dynamic_framerate for %s", device_id)
            except Exception as e:
                logger.debug("Could not set exposure_dynamic_framerate: %s", e)

        # Read a test frame to verify the camera works (with retry for cameras that need warmup)
        import time as _time
        for attempt in range(3):
            if attempt > 0:
                _time.sleep(0.2)
            success, _ = self._cap.read()
            if success:
                break
            logger.debug("USB camera %s test frame attempt %d failed, retrying...", self._dev_path, attempt + 1)
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
            logger.warning("USB camera %s: requested %.1f fps but camera reports %.1f fps",
                       self._dev_path, self._requested_fps, self._actual_fps)

        logger.info("USB camera opened successfully: %dx%d @ %.1f fps (requested %.1f)",
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
        self._capture_thread = thread  # Store reference for cleanup

        try:
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
        finally:
            # Ensure thread cleanup even if iterator is abandoned
            self._running = False
            if thread.is_alive():
                thread.join(timeout=2.0)
                if thread.is_alive():
                    logger.warning("Capture thread did not stop in time, proceeding with cleanup")
            self._capture_thread = None

    async def stop(self) -> None:
        self._running = False
        # Wait for capture thread to finish
        if hasattr(self, '_capture_thread') and self._capture_thread is not None:
            await asyncio.to_thread(self._capture_thread.join, timeout=2.0)
            self._capture_thread = None
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def set_control(self, name: str, value: Any) -> bool:
        """Set a USB camera control value via OpenCV or v4l2-ctl."""
        import sys
        import subprocess

        if not self._cap or not self._cap.isOpened():
            logger.warning("Cannot set control %s: camera not open", name)
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
                        logger.debug("Set USB control %s = %s via OpenCV (verified)", name, value)
                        return True
                    else:
                        logger.debug("OpenCV set %s returned True but value unchanged (old=%s, new=%s, target=%s)",
                                 name, old_value, new_value, cv_value)
            except Exception as e:
                logger.debug("OpenCV set error for %s: %s", name, e)

        # Use v4l2-ctl on Linux (primary method for unreliable controls, fallback for others)
        if sys.platform == "linux" and self._dev_path.startswith("/dev/video"):
            # Convert PascalCase to snake_case for v4l2
            v4l2_name = to_snake_case(name)
            try:
                result = subprocess.run(
                    ["v4l2-ctl", "-d", self._dev_path, f"--set-ctrl={v4l2_name}={int(cv_value)}"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
                if result.returncode == 0:
                    logger.debug("Set USB control %s = %s via v4l2-ctl", name, value)
                    return True
                else:
                    logger.debug("v4l2-ctl set failed for %s: %s", name, result.stderr.strip())
            except FileNotFoundError:
                logger.debug("v4l2-ctl not found")
            except subprocess.TimeoutExpired:
                logger.debug("v4l2-ctl timed out setting %s", name)
            except Exception as e:
                logger.debug("v4l2-ctl error setting %s: %s", name, e)

        logger.warning("Unable to set USB control %s", name)
        return False


async def open_capture(
    camera_type: str,
    camera_id: str,
    resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION,
    fps: float = DEFAULT_CAPTURE_FPS,
) -> Tuple[CaptureHandle, dict]:
    """
    Open a USB camera and return (capture_handle, capabilities).

    Args:
        camera_type: "usb" (only USB cameras supported in this module)
        camera_id: device path
        resolution: capture resolution (width, height)
        fps: target frame rate

    Returns:
        Tuple of (CaptureHandle, capabilities dict)
    """
    if camera_type != "usb":
        raise ValueError(f"Unsupported camera type: {camera_type}. This module only supports USB cameras.")

    capture = USBCapture(camera_id, resolution, fps)
    await capture.start()

    # Return actual FPS after camera opened - may differ from requested for USB cameras
    capabilities: dict = {
        "camera_type": camera_type,
        "camera_id": camera_id,
        "resolution": resolution,
        "requested_fps": fps,
        "actual_fps": capture.actual_fps,
    }

    return capture, capabilities


__all__ = ["CaptureFrame", "CaptureHandle", "USBCapture", "open_capture"]
