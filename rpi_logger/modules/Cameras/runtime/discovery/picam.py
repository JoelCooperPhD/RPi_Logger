"""Pi camera discovery/probing using Picamera2 when available."""

from __future__ import annotations

import asyncio
from typing import List, Optional

try:
    from picamera2 import Picamera2  # type: ignore
except Exception:  # pragma: no cover - picamera2 may be absent
    Picamera2 = None  # type: ignore

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import CameraDescriptor, CameraId
from .capabilities import build_capabilities


def discover_picam(logger: LoggerLike = None) -> List[CameraDescriptor]:
    """List CSI cameras via Picamera2."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    descriptors: list[CameraDescriptor] = []
    if Picamera2 is None:
        log.debug("Picamera2 not available; skipping CSI discovery")
        return descriptors

    try:
        cameras = Picamera2.global_camera_info()
    except Exception as exc:  # pragma: no cover - hardware dependent
        log.warning("Picamera2 discovery failed: %s", exc)
        return descriptors

    for idx, info in enumerate(cameras):
        model = info.get("Model") or ""
        cam_id = info.get("Id") or ""

        # Skip non-CSI cameras that show up via libcamera (e.g., UVC).
        if "usb@" in cam_id or model.lower().startswith("uvc"):
            log.debug("Skipping non-CSI camera entry: %s", cam_id or model)
            continue

        sensor_id = info.get("SensorId")
        stable_id = str(info.get("Num")) if info.get("Num") is not None else str(sensor_id or cam_id or idx)

        friendly_label = f"RPi:Cam{stable_id}" if str(stable_id).isdigit() else f"RPi:Cam{idx}"

        camera_id = CameraId(
            backend="picam",
            stable_id=stable_id,
            friendly_name=friendly_label,
        )
        descriptors.append(
            CameraDescriptor(
                camera_id=camera_id,
                hw_model=model or None,
                location_hint=cam_id or None,
            )
        )
    log.debug("Discovered %d Pi cameras", len(descriptors))
    return descriptors


async def probe_picam_capabilities(sensor_id: str, *, logger: LoggerLike = None):
    """Probe capabilities for a CSI camera using Picamera2."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    if Picamera2 is None:
        log.warning("Picamera2 not available; cannot probe sensor %s", sensor_id)
        return None
    return await asyncio.to_thread(_probe_picam_sync, sensor_id, log)


def _probe_picam_sync(sensor_id: str, log):
    try:
        cam = Picamera2(camera_num=int(sensor_id) if sensor_id.isdigit() else 0)
    except Exception as exc:
        log.warning("Failed to open Picamera2 sensor %s: %s", sensor_id, exc)
        fallback = _fallback_caps_from_global(sensor_id, log)
        if fallback:
            return fallback
        return None

    try:
        modes = []
        for cfg in cam.sensor_modes or []:
            size = cfg.get("size") or (cfg.get("width"), cfg.get("height"))
            fps = cfg.get("fps", cfg.get("framerate", 30))
            modes.append({"size": size, "fps": fps, "pixel_format": "RGB"})
        if not modes and cam.camera_configuration():
            # Fallback: use preview configuration metadata.
            cfg = cam.camera_configuration()
            size = (cfg["size"][0], cfg["size"][1])
            modes.append({"size": size, "fps": cfg.get("framerate", 30), "pixel_format": "RGB"})
    finally:
        cam.close()

    return build_capabilities(modes)


def _fallback_caps_from_global(sensor_id: str, log):
    """Best-effort capabilities when camera cannot be opened (e.g., busy)."""

    try:
        if Picamera2 is None:
            return None
        cameras = Picamera2.global_camera_info()
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("Fallback global_camera_info failed: %s", exc)
        return None

    entry = None
    for info in cameras:
        if str(info.get("Num")) == str(sensor_id) or str(info.get("Id")) == str(sensor_id):
            entry = info
            break
    if entry is None and cameras:
        try:
            entry = cameras[int(sensor_id)]
        except Exception:
            entry = cameras[0]

    if entry is None:
        return None

    # Conservative defaults if nothing else is available.
    guessed_modes = [
        {"size": (640, 480), "fps": 30, "pixel_format": "RGB"},
        {"size": (1280, 720), "fps": 30, "pixel_format": "RGB"},
    ]
    return build_capabilities(guessed_modes)


__all__ = ["discover_picam", "probe_picam_capabilities"]
