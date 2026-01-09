"""USB camera capability probing.

Probes camera hardware to discover supported modes (resolutions/framerates).
Returns raw probe results - filtering is handled by CameraKnowledge.
"""

import asyncio
from typing import Callable, Optional, Any
import logging

logger = logging.getLogger(__name__)

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


async def probe_camera_modes(
    device: int | str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> list[dict[str, Any]]:
    """Probe a camera device and return all supported modes.

    Returns raw modes - no filtering applied. Filtering is done by CameraKnowledge.
    """
    if on_progress:
        on_progress("Probing video modes...")

    modes = await asyncio.to_thread(_probe_modes_sync, device, on_progress)

    if not modes:
        raise RuntimeError(f"Failed to probe capabilities for {device}")

    if on_progress:
        on_progress("Probing complete")

    logger.info("Probed %d modes for %s", len(modes), device)
    return modes


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


async def verify_camera_accessible(device: int | str) -> bool:
    """Quick check if camera can be opened and read.

    Used to verify a known camera is still accessible before using cached modes.
    """
    def _verify():
        try:
            import cv2
        except ImportError:
            return False

        cap = cv2.VideoCapture(device)
        if not cap.isOpened():
            return False

        try:
            ret, _ = cap.read()
            return ret
        finally:
            cap.release()

    return await asyncio.to_thread(_verify)


# Keep old names for backwards compatibility during transition
probe_video_capabilities = probe_camera_modes
probe_video_quick = verify_camera_accessible
