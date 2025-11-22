"""Compatibility shim for the moved EyeTracker runtime."""

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)
logger.debug("eye_tracker_runtime shim imported")

from .app.eye_tracker_runtime import *  # noqa: F401,F403
