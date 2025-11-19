from rpi_logger.modules.base import ModuleInitializationError
from .constants import MODULE_NAME, MODULE_DESCRIPTION


class DRTInitializationError(ModuleInitializationError):
    pass


__all__ = [
    'MODULE_NAME',
    'MODULE_DESCRIPTION',
    'DRTInitializationError',
]
