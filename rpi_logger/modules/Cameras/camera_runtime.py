"""Compatibility shim for the moved Cameras runtime."""

from .logging_utils import get_module_logger

logger = get_module_logger(__name__)
logger.debug("camera_runtime shim imported")

from .app.camera_runtime import *  # noqa: F401,F403
