
from abc import ABC, abstractmethod
from typing import Any

from rpi_logger.core.logging_utils import get_module_logger

class BaseMode(ABC):

    def __init__(self, system: Any):
        self.system = system
        self.logger = get_module_logger(self.__class__.__name__)

    @abstractmethod
    async def run(self) -> None:
        raise NotImplementedError("Subclasses must implement run()")

    def is_running(self) -> bool:
        if not getattr(self.system, 'running', True):
            return False

        shutdown_event = getattr(self.system, 'shutdown_event', None)
        if shutdown_event is not None and shutdown_event.is_set():
            return False

        return True
