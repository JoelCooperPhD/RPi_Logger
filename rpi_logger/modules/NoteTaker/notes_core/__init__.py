
from rpi_logger.modules.base import ModuleInitializationError
from .constants import (
    MODULE_NAME,
    MODULE_DESCRIPTION,
    HEADERS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SESSION_PREFIX,
)


class NotesInitializationError(ModuleInitializationError):
    pass


from .notes_system import NotesSystem


__all__ = [
    "MODULE_NAME",
    "MODULE_DESCRIPTION",
    "HEADERS",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_SESSION_PREFIX",
    "NotesInitializationError",
    "NotesSystem",
]
