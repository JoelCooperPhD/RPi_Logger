
from typing import TYPE_CHECKING
from Modules.base.modes import BaseMode as CoreBaseMode

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem


class BaseMode(CoreBaseMode):

    def __init__(self, tracker_system: 'TrackerSystem'):
        super().__init__(tracker_system)

    async def start_recording(self) -> None:
        if not self.system.recording:
            if hasattr(self.system, 'recording_manager'):
                await self.system.recording_manager.toggle_recording()
                self.system.recording = True
                self.logger.info("Recording started")

    async def stop_recording(self) -> None:
        if self.system.recording:
            if hasattr(self.system, 'recording_manager'):
                await self.system.recording_manager.toggle_recording()
                self.system.recording = False
                self.logger.info("Recording stopped")
