
from typing import Type

from Modules.base import BaseSupervisor
from .audio_system import AudioSystem, AudioInitializationError
from .constants import DEVICE_DISCOVERY_RETRY


class AudioSupervisor(BaseSupervisor[AudioSystem, AudioInitializationError]):

    def __init__(self, args):
        super().__init__(args, default_retry_interval=DEVICE_DISCOVERY_RETRY)

    def create_system(self) -> AudioSystem:
        return AudioSystem(self.args)

    def get_initialization_error_type(self) -> Type[AudioInitializationError]:
        return AudioInitializationError
