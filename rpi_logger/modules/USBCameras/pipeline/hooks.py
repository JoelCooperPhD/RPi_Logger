"""Shared pipeline hook dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import numpy as np

from rpi_logger.modules.USBCameras.domain.frame import FramePayload
from rpi_logger.modules.USBCameras.io.storage import StorageWriteResult
from rpi_logger.modules.USBCameras.controller.slot import USBCameraSlot


@dataclass(slots=True)
class StorageHooks:
    """Callback bundle used by the storage consumer."""

    save_enabled: Callable[[], bool]
    session_dir_provider: Callable[[], Optional[Path]]
    frame_to_bgr: Callable[[Any, str, Optional[tuple[int, int]]], np.ndarray]
    resolve_video_fps: Callable[[USBCameraSlot], float]
    on_frame_written: Callable[[USBCameraSlot, FramePayload, StorageWriteResult, int], Awaitable[bool]]
    handle_failure: Callable[[USBCameraSlot, str], Awaitable[None]]


__all__ = ["StorageHooks"]
