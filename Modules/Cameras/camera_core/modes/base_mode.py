
from typing import TYPE_CHECKING
from Modules.base.modes import BaseMode as CoreBaseMode

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class BaseMode(CoreBaseMode):

    def __init__(self, camera_system: 'CameraSystem'):
        super().__init__(camera_system)

    async def start_recording_all(self) -> None:
        if not self.system.recording:
            started = await self.system.start_recording()
            if started:
                self.logger.info("Recording started")

    async def stop_recording_all(self) -> None:
        if self.system.recording:
            stopped = await self.system.stop_recording()
            if stopped:
                self.logger.info("Recording stopped")

    def update_preview_frames(self) -> list:
        return [cam.update_preview_cache() for cam in self.system.cameras]
