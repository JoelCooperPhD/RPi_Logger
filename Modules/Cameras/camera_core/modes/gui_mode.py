
import asyncio
import logging
from typing import TYPE_CHECKING

from Modules.base.modes import BaseGUIMode
from ..interfaces.gui import TkinterGUI
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


logger = logging.getLogger(__name__)


class GUIMode(BaseGUIMode):

    def __init__(self, camera_system: 'CameraSystem', enable_commands: bool = False):
        super().__init__(camera_system, enable_commands)

    def create_gui(self) -> TkinterGUI:
        gui = TkinterGUI(self.system, self.system.args)

        if self.system.cameras:
            gui.create_preview_canvases()

        return gui

    def create_command_handler(self, gui: TkinterGUI) -> CommandHandler:
        return CommandHandler(self.system, gui=gui)

    async def on_auto_start_recording(self) -> None:
        if self.gui:
            self.gui._start_recording()

    def update_preview(self) -> None:
        if self.gui and self.gui.root.winfo_exists():
            self.gui.update_preview_frames()

    async def on_devices_connected(self) -> None:
        if self.gui and self.gui.root.winfo_exists():
            self.gui.create_preview_canvases()
            self.gui.root.title(f"Camera System - {len(self.system.cameras)} Cameras")

    def create_tasks(self) -> list[asyncio.Task]:
        return super().create_tasks()

    async def cleanup(self) -> None:
        pass

    def _on_recording_state_changed(self, is_recording: bool) -> None:
        """
        Disable/enable camera toggle menu items based on recording state.
        Camera selection should not change during recording.
        """
        if not self.gui:
            return

        state = 'disabled' if is_recording else 'normal'

        for i in range(len(self.system.cameras)):
            try:
                self.gui.view_menu.entryconfig(f"Camera {i}", state=state)
            except Exception:
                pass
