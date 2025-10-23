
from Modules.base import ModuleInitializationError
from .constants import (
    MODULE_NAME,
    MODULE_DESCRIPTION,
    CSV_HEADERS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SESSION_PREFIX,
)


class NotesInitializationError(ModuleInitializationError):
    pass


__all__ = [
    "MODULE_NAME",
    "MODULE_DESCRIPTION",
    "CSV_HEADERS",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_SESSION_PREFIX",
    "NotesInitializationError",
]
