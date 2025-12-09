"""USB camera backend using OpenCV for frame capture."""

from __future__ import annotations

import asyncio
import concurrent.futures
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CapabilityMode, CameraCapabilities
from rpi_logger.modules.Cameras.runtime.capabilities import build_capabilities
from rpi_logger.modules.Cameras.runtime.state import ControlInfo, ControlType


# OpenCV control properties to probe
USB_CONTROL_PROPS: Dict[str, int] = {
    # Image controls
    "Brightness": cv2.CAP_PROP_BRIGHTNESS,
    "Contrast": cv2.CAP_PROP_CONTRAST,
    "Saturation": cv2.CAP_PROP_SATURATION,
    "Hue": cv2.CAP_PROP_HUE,
    "Gain": cv2.CAP_PROP_GAIN,
    "Gamma": cv2.CAP_PROP_GAMMA,
    # Exposure controls
    "Exposure": cv2.CAP_PROP_EXPOSURE,
    "AutoExposure": cv2.CAP_PROP_AUTO_EXPOSURE,
    # White balance
    "WhiteBalanceBlueU": cv2.CAP_PROP_WHITE_BALANCE_BLUE_U,
    "WhiteBalanceRedV": cv2.CAP_PROP_WHITE_BALANCE_RED_V,
    # Focus
    "Focus": cv2.CAP_PROP_FOCUS,
    "AutoFocus": cv2.CAP_PROP_AUTOFOCUS,
    "Zoom": cv2.CAP_PROP_ZOOM,
    # Other
    "Backlight": cv2.CAP_PROP_BACKLIGHT,
    "Pan": cv2.CAP_PROP_PAN,
    "Tilt": cv2.CAP_PROP_TILT,
}

# Controls that are boolean type
BOOLEAN_CONTROLS = {"AutoExposure", "AutoFocus"}


class DeviceLost(Exception):
    """Raised when the USB device disappears mid-capture."""


@dataclass(slots=True)
class USBFrame:
    data: np.ndarray
    timestamp: float  # monotonic seconds
    frame_number: int
    monotonic_ns: int
    sensor_timestamp_ns: Optional[int]
    wall_time: float
    wait_ms: float = 0.0
    color_format: str = "bgr"
    storage_queue_drops: int = 0


class USBHandle:
    """Async frame reader for a USB device."""

    def __init__(self, dev_path: str, mode: CapabilityMode, *, logger: LoggerLike = None) -> None:
        self.dev_path = dev_path
        self.mode = mode
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._cap = self._open_capture()
        self._frame_number = 0
        self._stopped = False
        self._running = False
        self._error: Optional[Exception] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue] = None
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="usbcam"
        )
        self._producer_future: Optional[concurrent.futures.Future] = None

    def _open_capture(self):
        """Prefer V4L2 backend on Linux, fallback to default."""

        import sys
        device_id = int(self.dev_path) if self.dev_path.isdigit() else self.dev_path

        default_backend = getattr(cv2, "CAP_V4L2", None) if sys.platform == "linux" else None
        backends = []
        if default_backend is not None:
            backends.append(default_backend)
        backends.append(None)  # OpenCV default

        last_error = None
        for backend in backends:
            try:
                cap = cv2.VideoCapture(device_id, backend) if backend is not None else cv2.VideoCapture(device_id)
            except Exception as exc:  # pragma: no cover - defensive
                last_error = str(exc)
                continue
            if cap and cap.isOpened():
                return cap
            try:
                if cap:
                    cap.release()
            except Exception:
                pass

        self._logger.warning("Unable to open USB device %s (backend error: %s)", self.dev_path, last_error)
        return None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=2)
        self._error = None
        await self._loop.run_in_executor(self._executor, self._configure)
        self._running = True
        self._producer_future = self._executor.submit(self._producer_loop)

    def _configure(self) -> None:
        if not self._cap:
            raise DeviceLost(f"USB device {self.dev_path} could not be opened")
        # Prefer MJPEG to avoid YUYV color issues on some UVC cams.
        try:
            fourcc = getattr(cv2, "VideoWriter_fourcc", lambda *args: 0)("M", "J", "P", "G")
            self._cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.mode.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.mode.height)
        target_fps = self.mode.fps if hasattr(self.mode, 'fps') and self.mode.fps else 30.0
        self._cap.set(cv2.CAP_PROP_FPS, target_fps)

    async def read_frame(self) -> USBFrame:
        queue = self._queue
        if queue is None:
            queue = asyncio.Queue()
            self._queue = queue
        frame, wait_ms, error = await queue.get()
        if frame is None:
            if error:
                raise error
            raise DeviceLost(f"USB device {self.dev_path} stopped")
        self._frame_number += 1
        monotonic_ns = time.monotonic_ns()
        wall_ts = time.time()
        return USBFrame(
            data=frame,
            timestamp=monotonic_ns / 1_000_000_000,
            frame_number=self._frame_number,
            monotonic_ns=monotonic_ns,
            sensor_timestamp_ns=None,
            wall_time=wall_ts,
            wait_ms=wait_ms,
        )

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._running = False
        loop = self._loop or asyncio.get_running_loop()
        if self._queue:
            try:
                loop.call_soon_threadsafe(self._offer_frame, None, 0.0, None, True)
            except Exception:
                pass
        if self._cap:
            await loop.run_in_executor(self._executor, self._release)
            self._cap = None
        self._shutdown_executor()

    def is_alive(self) -> bool:
        return bool(self._cap and self._cap.isOpened())

    def set_control(self, name: str, value: Any) -> bool:
        """Set a camera control value. Returns True on success."""
        if not self._cap or not self._cap.isOpened():
            self._logger.warning("Cannot set control %s: camera not open", name)
            return False

        # Try OpenCV property first
        prop_id = USB_CONTROL_PROPS.get(name)
        if prop_id is not None:
            try:
                # Convert booleans to int for OpenCV
                cv_value = int(value) if isinstance(value, bool) else value
                result = self._cap.set(prop_id, cv_value)
                if result:
                    self._logger.debug("Set control %s = %s via OpenCV", name, value)
                    return True
                else:
                    self._logger.debug("OpenCV set failed for %s, trying v4l2-ctl", name)
            except Exception as e:
                self._logger.debug("OpenCV set error for %s: %s", name, e)

        # Fallback to v4l2-ctl on Linux
        if sys.platform == "linux" and self.dev_path.startswith("/dev/video"):
            return self._set_control_v4l2(name, value)

        self._logger.warning("Unable to set control %s", name)
        return False

    def _set_control_v4l2(self, name: str, value: Any) -> bool:
        """Set control via v4l2-ctl (Linux only)."""
        # Convert PascalCase back to snake_case for v4l2
        v4l2_name = self._to_snake_case(name)

        try:
            # v4l2-ctl -d /dev/video0 --set-ctrl=brightness=128
            result = subprocess.run(
                ["v4l2-ctl", "-d", self.dev_path, f"--set-ctrl={v4l2_name}={value}"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if result.returncode == 0:
                self._logger.debug("Set control %s = %s via v4l2-ctl", name, value)
                return True
            else:
                self._logger.debug("v4l2-ctl set failed for %s: %s", name, result.stderr)
                return False
        except FileNotFoundError:
            self._logger.debug("v4l2-ctl not found")
            return False
        except subprocess.TimeoutExpired:
            self._logger.debug("v4l2-ctl timed out setting %s", name)
            return False
        except Exception as e:
            self._logger.debug("v4l2-ctl error setting %s: %s", name, e)
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

    # ------------------------------------------------------------------ producer

    def _producer_loop(self) -> None:
        while self._running:
            wait_start = time.perf_counter()
            success, frame = self._cap.read() if self._cap else (False, None)
            wait_ms = (time.perf_counter() - wait_start) * 1000.0
            if not success:
                self._error = DeviceLost(f"USB device {self.dev_path} lost or failed to read")
                self._running = False
                loop = self._loop
                if loop:
                    try:
                        loop.call_soon_threadsafe(self._offer_frame, None, wait_ms, self._error, True)
                    except Exception:
                        pass
                break
            loop = self._loop
            if not loop:
                continue
            try:
                loop.call_soon_threadsafe(self._offer_frame, frame, wait_ms, None, False)
            except Exception:
                pass
        loop = self._loop
        if loop:
            try:
                loop.call_soon_threadsafe(self._offer_frame, None, 0.0, self._error, True)
            except Exception:
                pass

    def _offer_frame(self, frame, wait_ms: float, error: Optional[Exception], sentinel: bool = False) -> None:
        queue = self._queue
        if not queue:
            return
        if sentinel:
            try:
                queue.put_nowait((None, wait_ms, error))
            except Exception:
                pass
            return
        if queue.full():
            try:
                queue.get_nowait()
            except Exception:
                pass
        try:
            queue.put_nowait((frame, wait_ms, None))
        except Exception:
            pass

    def _release(self) -> None:
        try:
            if self._cap:
                self._cap.release()
        except Exception:
            self._logger.debug("USB cap release failed", exc_info=True)

    def _shutdown_executor(self) -> None:
        if self._executor:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass
            self._executor = None


# ---------------------------------------------------------------------------
# Control probing functions


def _probe_controls_opencv(cap: cv2.VideoCapture, log) -> Dict[str, ControlInfo]:
    """Query available controls via OpenCV get/set probing."""
    controls: Dict[str, ControlInfo] = {}

    for name, prop_id in USB_CONTROL_PROPS.items():
        try:
            value = cap.get(prop_id)
            # OpenCV returns 0 or -1 for unsupported properties
            if value == -1:
                continue

            # Determine type
            if name in BOOLEAN_CONTROLS:
                control_type = ControlType.BOOLEAN
                current_value = bool(value)
            elif isinstance(value, float) and value != int(value):
                control_type = ControlType.FLOAT
                current_value = value
            else:
                control_type = ControlType.INTEGER
                current_value = int(value)

            controls[name] = ControlInfo(
                name=name,
                control_type=control_type,
                current_value=current_value,
                backend_id=prop_id,
            )
            log.debug("OpenCV control %s = %s (prop_id=%d)", name, current_value, prop_id)
        except Exception:
            continue

    return controls


def _probe_controls_v4l2(dev_path: str, log) -> Dict[str, ControlInfo]:
    """Query controls via v4l2-ctl for richer metadata (Linux only)."""
    controls: Dict[str, ControlInfo] = {}

    if not dev_path.startswith("/dev/video"):
        return controls

    try:
        # Use --list-ctrls-menus to get menu options as well
        result = subprocess.run(
            ["v4l2-ctl", "-d", dev_path, "--list-ctrls-menus"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if result.returncode != 0:
            log.debug("v4l2-ctl failed for %s: %s", dev_path, result.stderr)
            return controls
    except FileNotFoundError:
        log.debug("v4l2-ctl not found, skipping v4l2 control probe")
        return controls
    except subprocess.TimeoutExpired:
        log.debug("v4l2-ctl timed out for %s", dev_path)
        return controls
    except Exception as e:
        log.debug("v4l2-ctl error for %s: %s", dev_path, e)
        return controls

    # Parse lines like:
    # brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 value=128
    # auto_exposure 0x009a0901 (menu) : min=0 max=3 default=3 value=3 (Aperture Priority Mode)
    #                              1: Manual Mode
    #                              3: Aperture Priority Mode
    ctrl_pattern = r"^\s*(\w+)\s+0x[0-9a-f]+\s+\((\w+)\)\s*:\s*(.+)$"
    # Menu option lines are indented with format: "    N: Option Name"
    menu_pattern = r"^\s+(\d+):\s+(.+)$"

    current_ctrl_name: Optional[str] = None
    current_menu_options: List[tuple] = []  # List of (value, label) tuples

    lines = result.stdout.splitlines()
    for i, line in enumerate(lines):
        # Check for menu option line first (indented lines under menu controls)
        menu_match = re.match(menu_pattern, line)
        if menu_match and current_ctrl_name:
            option_value = int(menu_match.group(1))
            option_label = menu_match.group(2).strip()
            current_menu_options.append((option_value, option_label))
            continue

        # Check for control definition line
        ctrl_match = re.match(ctrl_pattern, line, re.IGNORECASE)
        if not ctrl_match:
            continue

        # Save menu options for the previous control if any
        if current_ctrl_name and current_menu_options:
            _update_control_options(controls, current_ctrl_name, current_menu_options, log)

        v4l2_name = ctrl_match.group(1)
        ctrl_type_str = ctrl_match.group(2).lower()
        attrs_str = ctrl_match.group(3)

        # Parse attributes: min=0 max=255 step=1 default=128 value=128
        attrs: Dict[str, int] = {}
        for attr in ["min", "max", "step", "default", "value"]:
            m = re.search(rf"{attr}=(-?\d+)", attrs_str)
            if m:
                attrs[attr] = int(m.group(1))

        # Determine control type
        if ctrl_type_str == "bool":
            control_type = ControlType.BOOLEAN
        elif ctrl_type_str == "menu":
            control_type = ControlType.ENUM
        elif ctrl_type_str == "int":
            control_type = ControlType.INTEGER
        else:
            control_type = ControlType.UNKNOWN

        # Normalize name to PascalCase for consistency
        display_name = _normalize_v4l2_name(v4l2_name)

        controls[display_name] = ControlInfo(
            name=display_name,
            control_type=control_type,
            current_value=attrs.get("value"),
            min_value=attrs.get("min"),
            max_value=attrs.get("max"),
            default_value=attrs.get("default"),
            step=float(attrs["step"]) if "step" in attrs else None,
            read_only=False,
            backend_id=v4l2_name,  # Original v4l2 control name
        )
        log.debug(
            "v4l2 control %s: type=%s min=%s max=%s default=%s value=%s",
            display_name,
            ctrl_type_str,
            attrs.get("min"),
            attrs.get("max"),
            attrs.get("default"),
            attrs.get("value"),
        )

        # Track current control for menu option parsing
        current_ctrl_name = display_name if ctrl_type_str == "menu" else None
        current_menu_options = []

    # Handle menu options for the last control
    if current_ctrl_name and current_menu_options:
        _update_control_options(controls, current_ctrl_name, current_menu_options, log)

    return controls


def _update_control_options(
    controls: Dict[str, ControlInfo],
    ctrl_name: str,
    menu_options: List[tuple],
    log,
) -> None:
    """Update a control with parsed menu options."""
    if ctrl_name not in controls:
        return

    old_ctrl = controls[ctrl_name]
    # Create option list as "value:label" strings for UI display
    options = [f"{val}:{label}" for val, label in menu_options]

    # Find the current value's label
    current_label = None
    for val, label in menu_options:
        if val == old_ctrl.current_value:
            current_label = f"{val}:{label}"
            break

    controls[ctrl_name] = ControlInfo(
        name=old_ctrl.name,
        control_type=old_ctrl.control_type,
        current_value=current_label or old_ctrl.current_value,
        min_value=old_ctrl.min_value,
        max_value=old_ctrl.max_value,
        default_value=old_ctrl.default_value,
        step=old_ctrl.step,
        options=options,
        read_only=old_ctrl.read_only,
        backend_id=old_ctrl.backend_id,
    )
    log.debug("Menu control %s options: %s (current=%s)", ctrl_name, options, current_label)


def _normalize_v4l2_name(name: str) -> str:
    """Convert v4l2 control name (snake_case) to PascalCase."""
    # e.g., "brightness" -> "Brightness", "auto_exposure" -> "AutoExposure"
    parts = name.split("_")
    return "".join(part.capitalize() for part in parts)


async def probe(dev_path: str, *, logger: LoggerLike = None) -> Optional[CameraCapabilities]:
    """Probe device modes in a thread."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    return await asyncio.to_thread(_probe_sync, dev_path, log)


def _probe_sync(dev_path: str, log) -> Optional[CameraCapabilities]:
    device_id = int(dev_path) if dev_path.isdigit() else dev_path

    cap = None
    default_backend = getattr(cv2, "CAP_V4L2", None) if sys.platform == "linux" else None
    backends = [b for b in (default_backend, None)]
    for backend in backends:
        try:
            cap = cv2.VideoCapture(device_id, backend) if backend is not None else cv2.VideoCapture(device_id)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("VideoCapture open failed for %s backend=%s: %s", dev_path, backend, exc)
            cap = None
            continue
        if cap and cap.isOpened():
            break
        if cap:
            cap.release()
            cap = None

    if not cap or not cap.isOpened():
        log.warning("Unable to open USB device %s", dev_path)
        return None

    modes: List[Dict] = []
    controls: Dict[str, ControlInfo] = {}
    validated = set()  # Track (w, h, fps) combos we've confirmed work

    try:
        try:
            fourcc = getattr(cv2, "VideoWriter_fourcc", lambda *args: 0)("M", "J", "P", "G")
            cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass

        # Probe video modes
        widths = [320, 640, 800, 1280, 1920]
        heights = [240, 480, 600, 720, 1080]
        fps_options = [15, 25, 30]
        for w, h in zip(widths, heights):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            for fps in fps_options:
                cap.set(cv2.CAP_PROP_FPS, fps)
                # Actually capture a frame to validate this mode works
                ret, frame = cap.read()
                if not ret or frame is None:
                    log.debug("Mode %dx%d@%d failed: no frame returned", w, h, fps)
                    continue
                actual_h, actual_w = frame.shape[:2]
                actual_fps = float(cap.get(cv2.CAP_PROP_FPS) or fps)
                # Round FPS to avoid floating point duplicates
                actual_fps = round(actual_fps, 1)
                key = (actual_w, actual_h, actual_fps)
                if key in validated:
                    continue
                validated.add(key)
                modes.append({"size": (actual_w, actual_h), "fps": actual_fps, "pixel_format": "MJPEG"})
                log.debug("Validated mode %dx%d@%.1f fps", actual_w, actual_h, actual_fps)

        # Probe controls - prefer v4l2-ctl for richer metadata, fallback to OpenCV
        if sys.platform == "linux" and isinstance(dev_path, str):
            controls = _probe_controls_v4l2(dev_path, log)
            if controls:
                log.info("Probed %d controls via v4l2-ctl for %s", len(controls), dev_path)
        if not controls:
            controls = _probe_controls_opencv(cap, log)
            if controls:
                log.info("Probed %d controls via OpenCV for %s", len(controls), dev_path)

    finally:
        cap.release()

    # Build capabilities and attach controls
    caps = build_capabilities(modes)
    caps.controls = controls
    return caps


async def open_device(dev_path: str, mode: CapabilityMode, *, logger: LoggerLike = None) -> USBHandle:
    handle = USBHandle(dev_path, mode, logger=logger)
    await handle.start()
    if not handle.is_alive():
        raise DeviceLost(f"USB device {dev_path} failed to start")
    return handle


__all__ = ["USBHandle", "USBFrame", "DeviceLost", "probe", "open_device"]
