import asyncio
from typing import Callable, Optional, Any

from ..core.state import CameraCapabilities


COMMON_RESOLUTIONS = [
    (320, 240),
    (640, 480),
    (800, 600),
    (1024, 768),
    (1280, 720),
    (1280, 960),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
]

COMMON_FPS = [5, 10, 15, 24, 25, 30, 60]


async def probe_video_capabilities(
    device: int | str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> CameraCapabilities:
    if on_progress:
        on_progress("Opening device...")

    modes = await asyncio.to_thread(_probe_modes_sync, device, on_progress)

    if not modes:
        raise RuntimeError(f"Failed to probe capabilities for {device}")

    default_resolution = (640, 480)
    default_fps = 30.0
    for mode in modes:
        size = mode.get("size", (0, 0))
        fps = mode.get("fps", 0)
        if size == (640, 480) and fps >= 30:
            default_resolution = size
            default_fps = fps
            break

    if on_progress:
        on_progress("Probing complete")

    camera_id = f"usb:{device}"
    return CameraCapabilities(
        camera_id=camera_id,
        modes=tuple(modes),
        controls={},
        default_resolution=default_resolution,
        default_fps=default_fps,
    )


def _probe_modes_sync(
    device: int | str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> list[dict[str, Any]]:
    try:
        import cv2
    except ImportError:
        raise RuntimeError("OpenCV (cv2) is required for USB camera probing")

    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open device {device}")

    modes = []
    tested_combos = set()

    try:
        if on_progress:
            on_progress("Testing resolutions...")

        for width, height in COMMON_RESOLUTIONS:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if (actual_w, actual_h) in tested_combos:
                continue
            tested_combos.add((actual_w, actual_h))

            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            if frame.shape[1] != actual_w or frame.shape[0] != actual_h:
                actual_w = frame.shape[1]
                actual_h = frame.shape[0]

            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                fps = 30.0

            modes.append({
                "size": (actual_w, actual_h),
                "fps": float(fps),
                "pixel_format": "MJPEG",
                "controls": {},
            })

        if not modes:
            ret, frame = cap.read()
            if ret and frame is not None:
                actual_w = frame.shape[1]
                actual_h = frame.shape[0]
                fps = cap.get(cv2.CAP_PROP_FPS)
                if fps <= 0:
                    fps = 30.0
                modes.append({
                    "size": (actual_w, actual_h),
                    "fps": float(fps),
                    "pixel_format": "MJPEG",
                    "controls": {},
                })

    finally:
        cap.release()

    modes.sort(key=lambda m: (m["size"][0] * m["size"][1], m["fps"]))
    return modes


async def probe_video_quick(device: int | str) -> CameraCapabilities:
    def _quick_probe():
        try:
            import cv2
        except ImportError:
            raise RuntimeError("OpenCV (cv2) is required")

        cap = cv2.VideoCapture(device)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open device {device}")

        try:
            ret, frame = cap.read()
            if not ret or frame is None:
                raise RuntimeError(f"Cannot read from {device}")

            width = frame.shape[1]
            height = frame.shape[0]
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                fps = 30.0

            return CameraCapabilities(
                camera_id=f"usb:{device}",
                modes=({"size": (width, height), "fps": fps, "pixel_format": "MJPEG", "controls": {}},),
                controls={},
                default_resolution=(width, height),
                default_fps=fps,
            )
        finally:
            cap.release()

    return await asyncio.to_thread(_quick_probe)
