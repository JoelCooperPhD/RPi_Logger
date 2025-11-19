
from typing import Type

from rpi_logger.modules.base import BaseSupervisor
from .tracker_system import TrackerSystem, TrackerInitializationError
from .constants import DEVICE_DISCOVERY_RETRY_SECONDS


class TrackerSupervisor(BaseSupervisor[TrackerSystem, TrackerInitializationError]):

    def __init__(self, args):
        super().__init__(args, default_retry_interval=DEVICE_DISCOVERY_RETRY_SECONDS)

    def create_system(self) -> TrackerSystem:
        return TrackerSystem(self.args)

    def get_initialization_error_type(self) -> Type[TrackerInitializationError]:
        return TrackerInitializationError

    def get_system_name(self) -> str:
        return "Eye tracker"
