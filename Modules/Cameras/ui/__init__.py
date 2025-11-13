"""View package for the Cameras runtime."""

from ..logging_utils import get_module_logger

logger = get_module_logger(__name__)
logger.debug("UI package initialized")

from .adapter import CameraViewAdapter

__all__ = ["CameraViewAdapter"]
