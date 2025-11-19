from rpi_logger.core.logging_utils import get_module_logger
from typing import Type

from rpi_logger.modules.base import BaseSupervisor
from . import DRTInitializationError
from .drt_system import DRTSystem


class DRTSupervisor(BaseSupervisor[DRTSystem, DRTInitializationError]):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = get_module_logger("DRTSupervisor")

    def create_system(self) -> DRTSystem:
        self.logger.debug("Creating DRTSystem instance")
        return DRTSystem(self.args)

    def get_initialization_error_type(self) -> Type[DRTInitializationError]:
        return DRTInitializationError
