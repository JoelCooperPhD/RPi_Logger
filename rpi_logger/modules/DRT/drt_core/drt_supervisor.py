import logging
from typing import Type

from Modules.base import BaseSupervisor
from . import DRTInitializationError
from .drt_system import DRTSystem

logger = logging.getLogger(__name__)


class DRTSupervisor(BaseSupervisor[DRTSystem, DRTInitializationError]):

    def create_system(self) -> DRTSystem:
        logger.debug("Creating DRTSystem instance")
        return DRTSystem(self.args)

    def get_initialization_error_type(self) -> Type[DRTInitializationError]:
        return DRTInitializationError
