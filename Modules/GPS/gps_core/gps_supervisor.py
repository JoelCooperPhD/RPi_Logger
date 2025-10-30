from typing import Type

from Modules.base import BaseSupervisor
from .gps_system import GPSSystem, GPSInitializationError


class GPSSupervisor(BaseSupervisor[GPSSystem, GPSInitializationError]):

    def __init__(self, args):
        super().__init__(args, default_retry_interval=3.0)

    def create_system(self) -> GPSSystem:
        return GPSSystem(self.args)

    def get_initialization_error_type(self) -> Type[GPSInitializationError]:
        return GPSInitializationError
