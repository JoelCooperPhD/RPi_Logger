"""USB camera backend using OpenCV."""

from __future__ import annotations

import asyncio, concurrent.futures, contextlib, re, subprocess, sys, time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.base.camera_types import CapabilityMode, CameraCapabilities, ControlInfo, ControlType
from rpi_logger.modules.Cameras.camera_core.capabilities import build_capabilities
from rpi_logger.modules.Cameras.utils import set_usb_control_v4l2, to_snake_case, open_videocapture

USB_CONTROL_PROPS: Dict[str, int] = {
    "Brightness": cv2.CAP_PROP_BRIGHTNESS, "Contrast": cv2.CAP_PROP_CONTRAST,
    "Saturation": cv2.CAP_PROP_SATURATION, "Hue": cv2.CAP_PROP_HUE,
    "Gain": cv2.CAP_PROP_GAIN, "Gamma": cv2.CAP_PROP_GAMMA,
    "Exposure": cv2.CAP_PROP_EXPOSURE, "AutoExposure": cv2.CAP_PROP_AUTO_EXPOSURE,
    "WhiteBalanceBlueU": cv2.CAP_PROP_WHITE_BALANCE_BLUE_U, "WhiteBalanceRedV": cv2.CAP_PROP_WHITE_BALANCE_RED_V,
    "Focus": cv2.CAP_PROP_FOCUS, "AutoFocus": cv2.CAP_PROP_AUTOFOCUS,
    "Zoom": cv2.CAP_PROP_ZOOM, "Backlight": cv2.CAP_PROP_BACKLIGHT,
    "Pan": cv2.CAP_PROP_PAN, "Tilt": cv2.CAP_PROP_TILT,
}
BOOLEAN_CONTROLS = {"AutoExposure", "AutoFocus"}


class DeviceLost(Exception):
    """USB device disappeared."""


@dataclass(slots=True)
class USBFrame:
    data: np.ndarray
    timestamp: float
    frame_number: int
    monotonic_ns: int
    sensor_timestamp_ns: Optional[int]
    wall_time: float
    wait_ms: float = 0.0
    color_format: str = "bgr"
    storage_queue_drops: int = 0


class USBHandle:
    """Async frame reader for USB device."""

    def __init__(self, dev_path: str, mode: CapabilityMode, *, logger: LoggerLike = None) -> None:
        self.dev_path, self.mode = dev_path, mode
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._cap = open_videocapture(dev_path, logger=self._logger)
        self._frame_number, self._stopped, self._running = 0, False, False
        self._error: Optional[Exception] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue] = None
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="usbcam")
        self._producer_future: Optional[concurrent.futures.Future] = None

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
        with contextlib.suppress(Exception):
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc("M", "J", "P", "G"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.mode.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.mode.height)
        self._cap.set(cv2.CAP_PROP_FPS, getattr(self.mode, 'fps', 30.0))

    async def read_frame(self) -> USBFrame:
        if self._queue is None:
            self._queue = asyncio.Queue()
        frame, wait_ms, error = await self._queue.get()
        if frame is None:
            raise error if error else DeviceLost(f"USB device {self.dev_path} stopped")
        self._frame_number += 1
        mono_ns = time.monotonic_ns()
        return USBFrame(data=frame, timestamp=mono_ns / 1e9, frame_number=self._frame_number, monotonic_ns=mono_ns, sensor_timestamp_ns=None, wall_time=time.time(), wait_ms=wait_ms)

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped, self._running = True, False
        loop = self._loop or asyncio.get_running_loop()
        if self._queue:
            with contextlib.suppress(Exception):
                loop.call_soon_threadsafe(self._offer_frame, None, 0.0, None, True)
        if self._cap:
            await loop.run_in_executor(self._executor, self._release)
            self._cap = None
        if self._executor:
            with contextlib.suppress(Exception):
                self._executor.shutdown(wait=False)
            self._executor = None

    def is_alive(self) -> bool:
        return bool(self._cap and self._cap.isOpened())

    def set_control(self, name: str, value: Any) -> bool:
        """Set camera control. Returns True on success."""
        if not self._cap or not self._cap.isOpened():
            return False
        prop_id = USB_CONTROL_PROPS.get(name)
        if prop_id is not None:
            with contextlib.suppress(Exception):
                if self._cap.set(prop_id, int(value) if isinstance(value, bool) else value):
                    return True
        return set_usb_control_v4l2(self.dev_path, name, value, logger=self._logger)

    def _producer_loop(self) -> None:
        while self._running:
            t0 = time.perf_counter()
            success, frame = self._cap.read() if self._cap else (False, None)
            wait_ms = (time.perf_counter() - t0) * 1000.0
            if not success:
                self._error = DeviceLost(f"USB device {self.dev_path} lost")
                self._running = False
                if self._loop:
                    with contextlib.suppress(Exception):
                        self._loop.call_soon_threadsafe(self._offer_frame, None, wait_ms, self._error, True)
                break
            if self._loop:
                with contextlib.suppress(Exception):
                    self._loop.call_soon_threadsafe(self._offer_frame, frame, wait_ms, None, False)
        if self._loop:
            with contextlib.suppress(Exception):
                self._loop.call_soon_threadsafe(self._offer_frame, None, 0.0, self._error, True)

    def _offer_frame(self, frame, wait_ms: float, error: Optional[Exception], sentinel: bool = False) -> None:
        if not self._queue:
            return
        if sentinel:
            with contextlib.suppress(Exception):
                self._queue.put_nowait((None, wait_ms, error))
            return
        if self._queue.full():
            with contextlib.suppress(Exception):
                self._queue.get_nowait()
        with contextlib.suppress(Exception):
            self._queue.put_nowait((frame, wait_ms, None))

    def _release(self) -> None:
        with contextlib.suppress(Exception):
            if self._cap:
                self._cap.release()


def _probe_controls_opencv(cap: cv2.VideoCapture, log) -> Dict[str, ControlInfo]:
    """Query controls via OpenCV."""
    controls: Dict[str, ControlInfo] = {}
    for name, prop_id in USB_CONTROL_PROPS.items():
        with contextlib.suppress(Exception):
            value = cap.get(prop_id)
            if value == -1:
                continue
            if name in BOOLEAN_CONTROLS:
                ct, cv = ControlType.BOOLEAN, bool(value)
            elif isinstance(value, float) and value != int(value):
                ct, cv = ControlType.FLOAT, value
            else:
                ct, cv = ControlType.INTEGER, int(value)
            controls[name] = ControlInfo(name=name, control_type=ct, current_value=cv, backend_id=prop_id)
    return controls


def _probe_controls_v4l2(dev_path: str, log) -> Dict[str, ControlInfo]:
    """Query controls via v4l2-ctl (Linux only)."""
    controls: Dict[str, ControlInfo] = {}
    if not dev_path.startswith("/dev/video"):
        return controls
    try:
        result = subprocess.run(["v4l2-ctl", "-d", dev_path, "--list-ctrls-menus"], capture_output=True, text=True, timeout=5.0)
        if result.returncode != 0:
            return controls
    except Exception:
        return controls

    ctrl_pat = r"^\s*(\w+)\s+0x[0-9a-f]+\s+\((\w+)\)\s*:\s*(.+)$"
    menu_pat = r"^\s+(\d+):\s+(.+)$"
    current_ctrl, menu_opts = None, []
    type_map = {"bool": ControlType.BOOLEAN, "menu": ControlType.ENUM, "int": ControlType.INTEGER}

    for line in result.stdout.splitlines():
        if (mm := re.match(menu_pat, line)) and current_ctrl:
            menu_opts.append((int(mm.group(1)), mm.group(2).strip()))
            continue
        if not (cm := re.match(ctrl_pat, line, re.IGNORECASE)):
            continue
        if current_ctrl and menu_opts:
            _update_menu_opts(controls, current_ctrl, menu_opts)
        v4l2_name, tstr, attrs_str = cm.group(1), cm.group(2).lower(), cm.group(3)
        attrs = {a: int(m.group(1)) for a in ["min", "max", "step", "default", "value"] if (m := re.search(rf"{a}=(-?\d+)", attrs_str))}
        name = "".join(p.capitalize() for p in v4l2_name.split("_"))
        controls[name] = ControlInfo(name=name, control_type=type_map.get(tstr, ControlType.UNKNOWN), current_value=attrs.get("value"), min_value=attrs.get("min"), max_value=attrs.get("max"), default_value=attrs.get("default"), step=float(attrs["step"]) if "step" in attrs else None, read_only=False, backend_id=v4l2_name)
        current_ctrl, menu_opts = (name if tstr == "menu" else None), []
    if current_ctrl and menu_opts:
        _update_menu_opts(controls, current_ctrl, menu_opts)
    return controls


def _update_menu_opts(controls: Dict[str, ControlInfo], name: str, opts: List[tuple]) -> None:
    if name not in controls:
        return
    old = controls[name]
    options = [f"{v}:{l}" for v, l in opts]
    cur_label = next((f"{v}:{l}" for v, l in opts if v == old.current_value), old.current_value)
    controls[name] = ControlInfo(name=old.name, control_type=old.control_type, current_value=cur_label, min_value=old.min_value, max_value=old.max_value, default_value=old.default_value, step=old.step, options=options, read_only=old.read_only, backend_id=old.backend_id)


async def probe(dev_path: str, *, logger: LoggerLike = None) -> Optional[CameraCapabilities]:
    return await asyncio.to_thread(_probe_sync, dev_path, ensure_structured_logger(logger, fallback_name=__name__))


def _probe_sync(dev_path: str, log) -> Optional[CameraCapabilities]:
    cap = open_videocapture(dev_path, logger=log)
    if not cap:
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
