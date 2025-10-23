
from typing import TYPE_CHECKING
from Modules.base.modes import BaseMode as CoreBaseMode

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class BaseMode(CoreBaseMode):

    def __init__(self, camera_system: 'CameraSystem'):
        super().__init__(camera_system)

    def start_recording_all(self) -> None:
        if not self.system.recording:
            session_dir = self.system._ensure_session_dir()
            for cam in self.system.cameras:
                cam.start_recording(session_dir)
            self.system.recording = True
            self.logger.info("Recording started")

    def stop_recording_all(self) -> None:
        if self.system.recording:
            for cam in self.system.cameras:
                cam.stop_recording()
            self.system.recording = False
            self.logger.info("Recording stopped")

    def update_preview_frames(self) -> list:
        return [cam.update_preview_cache() for cam in self.system.cameras]
