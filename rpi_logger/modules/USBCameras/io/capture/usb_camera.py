"""Thin wrapper around OpenCV VideoCapture for USB devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

try:
    import cv2
except Exception:  # pragma: no cover - defensive import
    cv2 = None

from rpi_logger.core.logging_utils import ensure_structured_logger


@dataclass(slots=True)
class USBCameraInfo:
    """Represents a discovered USB camera."""

    index: int
    path: str
    name: str
    native_size: Optional[Tuple[int, int]] = None


class USBCamera:
    """OpenCV-backed capture helper for USB cameras."""

    def __init__(
        self,
        info: USBCameraInfo,
        *,
        target_size: Optional[Tuple[int, int]] = None,
        target_fps: Optional[float] = None,
        backend: Optional[int] = None,
        logger=None,
        auto_balance: bool = True,
    ) -> None:
        self.info = info
        self.target_size = target_size
        self.target_fps = target_fps
        self.backend = backend
        self.auto_balance = auto_balance
        self.logger = ensure_structured_logger(
            logger,
            component=f"USBCamera.{info.index}",
            fallback_name=f"{__name__}.USBCamera.{info.index}",
        )
        self._cap: Optional[Any] = None
        self._opened = False

    @property
    def is_open(self) -> bool:
        return bool(self._opened)

    @property
    def device_path(self) -> str:
        return self.info.path

    def start(self) -> bool:
        if cv2 is None:
            self.logger.error("OpenCV is unavailable; cannot open USB camera %s", self.info.index)
            return False

        if self._opened:
            return True

        default_backend = getattr(cv2, "CAP_V4L2", None)
        backends = [self.backend] if self.backend is not None else []
        if default_backend is not None:
            backends.append(default_backend)
        backends.append(None)  # final fallback to OpenCV default

        self.logger.info(
            "Opening USB camera %s (%s) | target_size=%s target_fps=%s backends=%s",
            self.info.index,
            self.device_path,
            self.target_size,
            self.target_fps,
            backends,
        )

        opened = False
        last_error: Optional[str] = None
        for backend in backends:
            try:
                self._cap = cv2.VideoCapture(self.info.index, backend) if backend is not None else cv2.VideoCapture(
                    self.info.index
                )
            except Exception as exc:  # pragma: no cover - defensive
                last_error = str(exc)
                self._cap = None
                continue

            if self._cap and self._cap.isOpened():
                opened = True
                break
            else:
                try:
                    if self._cap:
                        self._cap.release()
                except Exception:
                    pass
                self._cap = None

        if not opened or not self._cap:
            self.logger.error(
                "Camera %s could not be opened (path=%s backend_tried=%s last_error=%s)",
                self.info.index,
                self.device_path,
                backends,
                last_error,
            )
            return False

        if self.target_size:
            width, height = self.target_size
            try:
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            except Exception:
                pass

        # Prefer MJPEG to avoid incorrect YUYV conversions that can skew colors on some UVC cams.
        try:
            fourcc = getattr(cv2, "VideoWriter_fourcc", lambda *args: 0)("M", "J", "P", "G")
            self._cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass

        if self.target_fps and self.target_fps > 0:
            try:
                self._cap.set(cv2.CAP_PROP_FPS, float(self.target_fps))
            except Exception:
                pass

        try:
            width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if width > 0 and height > 0:
                self.info.native_size = (width, height)
        except Exception:
            pass

        self.logger.info(
            "USB camera %s opened | resolved_size=%s fps_hint=%s",
            self.info.index,
            self.info.native_size,
            self.target_fps,
        )

        # Nudge white balance; many UVC devices ship with a cool/blue bias.
        self._configure_white_balance()

        self._opened = True
        return True

    def read(self) -> tuple[bool, Optional[Any], dict]:
        if not self._cap or not self._opened:
            return False, None, {}
        try:
            ok, frame = self._cap.read()
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("Capture failed for camera %s: %s", self.info.index, exc)
            return False, None, {}

        if ok and frame is not None and self.auto_balance:
            try:
                frame = self._balance_channels(frame)
            except Exception:
                pass

        metadata = {
            "usb_index": self.info.index,
            "device_path": self.device_path,
        }
        return bool(ok), frame, metadata

    def stop(self) -> None:
        if self._cap is None:
            return
        try:
            self._cap.release()
        except Exception:
            pass
        self._cap = None
        self._opened = False

    def _configure_white_balance(self) -> None:
        if cv2 is None or not self._cap:
            return
        try:
            auto_wb = getattr(cv2, "CAP_PROP_AUTO_WB", None)
            if auto_wb is not None:
                self._cap.set(auto_wb, 1)
            wb_temp = getattr(cv2, "CAP_PROP_WB_TEMPERATURE", None) or getattr(cv2, "CAP_PROP_TEMPERATURE", None)
            if wb_temp is not None:
                # 4600K is a neutral daylight-ish midpoint that counters a blue cast.
                self._cap.set(wb_temp, 4600)
        except Exception:
            pass

    def _balance_channels(self, frame):
        """Apply a simple gray-world white balance to reduce blue cast."""
        if frame is None:
            return frame
        if frame.ndim != 3 or frame.shape[2] < 3:
            return frame
        b, g, r = cv2.split(frame)
        b_avg, g_avg, r_avg = [chan.mean() for chan in (b, g, r)]
        mean_gray = (b_avg + g_avg + r_avg) / 3.0
        # Avoid division by zero, clamp gains reasonably.
        gains = []
        for avg in (b_avg, g_avg, r_avg):
            if avg <= 1e-3:
                gains.append(1.0)
            else:
                gains.append(mean_gray / avg)
        gains = [min(3.0, max(0.3, g)) for g in gains]
        b = cv2.multiply(b, gains[0])
        g = cv2.multiply(g, gains[1])
        r = cv2.multiply(r, gains[2])
        balanced = cv2.merge((b, g, r))
        balanced = cv2.threshold(balanced, 255, 255, cv2.THRESH_TRUNC)[1]
        return balanced.astype(frame.dtype, copy=False)


__all__ = ["USBCamera", "USBCameraInfo"]
