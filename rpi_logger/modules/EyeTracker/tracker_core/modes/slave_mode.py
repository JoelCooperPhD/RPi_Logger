
import logging
from typing import TYPE_CHECKING

from .base_mode import BaseMode
from logger_core.commands import BaseSlaveMode, BaseCommandHandler, StatusMessage
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem

logger = logging.getLogger(__name__)


class SlaveMode(BaseSlaveMode, BaseMode):

    def __init__(self, tracker_system: 'TrackerSystem'):
        BaseSlaveMode.__init__(self, tracker_system)
        BaseMode.__init__(self, tracker_system)

    def create_command_handler(self) -> BaseCommandHandler:
        return CommandHandler(self.system)

    async def _main_loop(self) -> None:
        try:
            await self.system.tracker_handler.run_foreground(display_enabled=False)
        except Exception as e:
            self.logger.error("Tracker error: %s", e, exc_info=True)
            StatusMessage.send("error", {"message": f"Tracker error: {str(e)[:100]}"})

    async def _on_ready(self) -> None:
        StatusMessage.send("initialized", {"message": "Eye tracker slave mode ready"})
