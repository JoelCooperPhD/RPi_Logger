"""Shared utility functions for the Cameras module."""
from __future__ import annotations

from typing import Any, Tuple

Resolution = Tuple[int, int]


def parse_resolution(raw: Any, default: Resolution = None) -> Resolution:
    """Parse resolution from tuple/list, 'WxH' string, or 'W,H' string.

    Returns default if parsing fails. Raises ValueError if no default.
    """
    if raw is None or raw == "":
        if default is None:
            raise ValueError("Invalid resolution format")
        return default
    try:
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            return int(raw[0]), int(raw[1])
        if isinstance(raw, str):
            s = raw.strip().lower()
            if "x" in s:
                w, h = s.split("x", 1)
                return int(w.strip()), int(h.strip())
            if "," in s:
                w, h = s.split(",", 1)
                return int(w.strip()), int(h.strip())
    except Exception:
        pass
    if default is None:
        raise ValueError(f"Invalid resolution: {raw!r}")
    return default


def to_snake_case(name: str) -> str:
    """Convert PascalCase to snake_case for v4l2 control names."""
    result = []
    for i, char in enumerate(name):
        if i > 0 and char.isupper():
            result.append("_")
        result.append(char.lower())
    return "".join(result)


def set_usb_control_v4l2(dev_path: str, name: str, value: Any, *, logger=None) -> bool:
    """Set USB camera control via v4l2-ctl (Linux only)."""
    import sys, subprocess
    if sys.platform != "linux" or not dev_path.startswith("/dev/video"):
        return False
    v4l2_name = to_snake_case(name)
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", dev_path, f"--set-ctrl={v4l2_name}={int(value)}"],
            capture_output=True, text=True, timeout=2.0
        )
        if result.returncode == 0:
            if logger:
                logger.debug("Set control %s = %s via v4l2-ctl", name, value)
            return True
        if logger:
            logger.debug("v4l2-ctl set failed for %s: %s", name, result.stderr.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        if logger:
            logger.debug("v4l2-ctl error for %s: %s", name, e)
    except Exception as e:
        if logger:
            logger.debug("v4l2-ctl error setting %s: %s", name, e)
    return False


def open_videocapture(dev_path: str, *, logger=None):
    """Open cv2.VideoCapture with V4L2 backend (Linux) or default."""
    import sys, cv2
    device_id = int(dev_path) if dev_path.isdigit() else dev_path
    backends = [getattr(cv2, "CAP_V4L2", None) if sys.platform == "linux" else None, None]

    last_error = None
    for backend in backends:
        try:
            cap = cv2.VideoCapture(device_id, backend) if backend else cv2.VideoCapture(device_id)
        except Exception as exc:
            last_error = str(exc)
            continue
        if cap and cap.isOpened():
            return cap
        try:
            if cap:
                cap.release()
        except Exception:
            pass

    if logger:
        logger.warning("Unable to open USB device %s (error: %s)", dev_path, last_error)
    return None


__all__ = ["Resolution", "parse_resolution", "to_snake_case", "set_usb_control_v4l2", "open_videocapture"]
