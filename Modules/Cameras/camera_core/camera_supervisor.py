
from typing import Type

from Modules.base import BaseSupervisor
from .camera_system import CameraSystem, CameraInitializationError


class CameraSupervisor(BaseSupervisor[CameraSystem, CameraInitializationError]):

    def __init__(self, args):
        super().__init__(args, default_retry_interval=3.0)

    def create_system(self) -> CameraSystem:
        return CameraSystem(self.args)

    def get_initialization_error_type(self) -> Type[CameraInitializationError]:
        return CameraInitializationError
