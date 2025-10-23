
import logging
from typing import Type

from Modules.base import BaseSupervisor
from . import NotesInitializationError
from .notes_system import NotesSystem

logger = logging.getLogger(__name__)


class NotesSupervisor(BaseSupervisor[NotesSystem, NotesInitializationError]):

    def create_system(self) -> NotesSystem:
        logger.debug("Creating NotesSystem instance")
        return NotesSystem(self.args)

    def get_initialization_error_type(self) -> Type[NotesInitializationError]:
        return NotesInitializationError
