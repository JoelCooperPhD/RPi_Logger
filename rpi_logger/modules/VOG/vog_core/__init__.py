"""VOG core module."""

from rpi_logger.modules.base import ModuleInitializationError
from .constants import MODULE_NAME, MODULE_DESCRIPTION


class VOGInitializationError(ModuleInitializationError):
    """Raised when VOG module fails to initialize."""
    pass


__all__ = [
    'MODULE_NAME',
    'MODULE_DESCRIPTION',
    'VOGInitializationError',
]
