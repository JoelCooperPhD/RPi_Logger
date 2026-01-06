"""USB camera capture via OpenCV/V4L2 (in-process)."""
from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Optional, Tuple

from rpi_logger.modules.Cameras.config import DEFAULT_CAPTURE_RESOLUTION, DEFAULT_CAPTURE_FPS
from rpi_logger.modules.Cameras.utils import set_usb_control_v4l2, open_videocapture
from rpi_logger.modules.base.camera_types import CaptureFrame, CaptureHandle
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


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
        import sys, cv2

        logger.info("Opening USB camera: %s", self._dev_path)
        self._cap = open_videocapture(self._dev_path, logger=logger)
        if not self._cap:
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
        if sys.platform == "linux" and isinstance(self._dev_path, str) and self._dev_path.startswith("/dev/video"):
            import subprocess
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    ["v4l2-ctl", "-d", self._dev_path, "-c", "exposure_dynamic_framerate=0"],
                    capture_output=True,
                    timeout=2.0
                )
            except Exception:
                pass

        # Read a test frame to verify the camera works (with retry for cameras that need warmup)
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(0.2)
            success, _ = await asyncio.to_thread(self._cap.read)
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
                await asyncio.to_thread(thread.join, 2.0)
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
        """Set camera control via OpenCV or v4l2-ctl."""
        import sys, subprocess, cv2

        if not self._cap or not self._cap.isOpened():
            logger.warning("Cannot set control %s: camera not open", name)
            return False
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

        # Controls unreliable in OpenCV - use v4l2-ctl directly
        OPENCV_UNRELIABLE_CONTROLS = {"Gain", "AutoExposure", "Exposure"}

        cv_value = int(value) if isinstance(value, bool) else value

        prop_id = CV_CONTROL_PROPS.get(name)
        if prop_id is not None and name not in OPENCV_UNRELIABLE_CONTROLS:
            try:
                old_value = self._cap.get(prop_id)
                result = self._cap.set(prop_id, cv_value)
                if result:
                    new_value = self._cap.get(prop_id)
                    if abs(new_value - cv_value) < 1.0:  # Verify change
                        logger.debug("Set USB control %s = %s via OpenCV (verified)", name, value)
                        return True
                    else:
                        logger.debug("OpenCV set %s returned True but value unchanged (old=%s, new=%s, target=%s)",
                                 name, old_value, new_value, cv_value)
            except Exception as e:
                logger.debug("OpenCV set error for %s: %s", name, e)

        if set_usb_control_v4l2(self._dev_path, name, cv_value, logger=logger):
            return True

        logger.warning("Unable to set USB control %s", name)
        return False


async def open_capture(
    camera_type: str,
    camera_id: str,
    resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION,
    fps: float = DEFAULT_CAPTURE_FPS,
) -> Tuple[CaptureHandle, dict]:
    """Open USB camera and return (handle, capabilities dict)."""
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


__all__ = ["USBCapture", "open_capture"]
