"""Local fallbacks for camera module constants."""

from __future__ import annotations

from ...logging_utils import get_module_logger

logger = get_module_logger(__name__)

try:
    from rpi_logger.modules.Cameras.camera_core.constants import (  # type: ignore
        CSV_FLUSH_INTERVAL_FRAMES as _CSV_FLUSH_INTERVAL_FRAMES,
        CSV_LOGGER_STOP_TIMEOUT_SECONDS as _CSV_LOGGER_STOP_TIMEOUT_SECONDS,
        CSV_QUEUE_SIZE as _CSV_QUEUE_SIZE,
        FRAME_LOG_COUNT as _FRAME_LOG_COUNT,
    )
except ModuleNotFoundError:
    logger.debug("camera_core constants unavailable; using local fallbacks")
    _CSV_FLUSH_INTERVAL_FRAMES = 60
    _CSV_LOGGER_STOP_TIMEOUT_SECONDS = 5.0
    _CSV_QUEUE_SIZE = 300
    _FRAME_LOG_COUNT = 3

CSV_FLUSH_INTERVAL_FRAMES = _CSV_FLUSH_INTERVAL_FRAMES
CSV_LOGGER_STOP_TIMEOUT_SECONDS = _CSV_LOGGER_STOP_TIMEOUT_SECONDS
CSV_QUEUE_SIZE = _CSV_QUEUE_SIZE
FRAME_LOG_COUNT = _FRAME_LOG_COUNT

__all__ = [
    "CSV_FLUSH_INTERVAL_FRAMES",
    "CSV_LOGGER_STOP_TIMEOUT_SECONDS",
    "CSV_QUEUE_SIZE",
    "FRAME_LOG_COUNT",
]
