
from typing import TYPE_CHECKING

from .base_mode import BaseMode
from logger_core.commands import BaseSlaveMode, BaseCommandHandler
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class SlaveMode(BaseSlaveMode, BaseMode):

    def __init__(self, audio_system: 'AudioSystem'):
        BaseSlaveMode.__init__(self, audio_system)
        BaseMode.__init__(self, audio_system)

    def create_command_handler(self) -> BaseCommandHandler:
        return CommandHandler(self.system)

    async def _on_ready(self) -> None:
        from logger_core.commands import StatusMessage
        StatusMessage.send("initialized", {"message": "Audio slave mode ready"})
