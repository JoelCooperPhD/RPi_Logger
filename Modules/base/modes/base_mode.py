
import logging
from abc import ABC, abstractmethod
from typing import Any


class BaseMode(ABC):

    def __init__(self, system: Any):
        self.system = system
        self.logger = logging.getLogger(self.__class__.__name__)

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
