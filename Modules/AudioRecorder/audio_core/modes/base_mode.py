
from typing import TYPE_CHECKING
from Modules.base.modes import BaseMode as CoreBaseMode

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class BaseMode(CoreBaseMode):

    def __init__(self, audio_system: 'AudioSystem'):
        super().__init__(audio_system)
