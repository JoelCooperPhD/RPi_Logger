"""Controller package for the Cameras runtime."""

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)
logger.debug("Controller package initialized")

from .orchestration import CameraController

__all__ = ["CameraController"]
