
import asyncio
import logging
from typing import TYPE_CHECKING

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base.modes import BaseGUIMode
from ..interfaces.gui import TkinterGUI
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem


logger = get_module_logger("EyeTracker.GUIMode")


class GUIMode(BaseGUIMode):

    def __init__(self, tracker_system: "TrackerSystem", enable_commands: bool = False):
        super().__init__(tracker_system, enable_commands)
        self.gaze_tracker = None
        self.tracker_task = None

    def create_gui(self) -> TkinterGUI:
        gui = TkinterGUI(self.system, self.system.args)

        self.gaze_tracker = self.system.tracker_handler.ensure_tracker(display_enabled=False)

        return gui

    def create_command_handler(self, gui: TkinterGUI) -> CommandHandler:
        return CommandHandler(self.system, gui=gui)

    async def on_auto_start_recording(self) -> None:
        await asyncio.sleep(3.0)

        if not self.system.recording_manager.is_recording:
            self.logger.info("Auto-starting recording...")
            await self.system.start_recording()
        else:
            self.logger.info("Recording already started")

    async def on_devices_connected(self) -> None:
        self.gaze_tracker = await self.system.tracker_handler.start_background(display_enabled=False)

        if self.gui and self.gui.root.winfo_exists():
            self.gui.root.title("Eye Tracker - Connected")

    def create_tasks(self) -> list[asyncio.Task]:
        tasks = super().create_tasks()

        if self.system.initialized:
            tasks.append(asyncio.create_task(
                self.system.tracker_handler.start_background(display_enabled=False)
            ))

        return tasks

    def update_preview(self) -> None:
        if self.gui and self.gui.root.winfo_exists():
            self.gui.update_preview_frame()

    def get_preview_update_interval(self) -> float:
        return 1.0 / getattr(self.system.args, 'gui_preview_update_hz', 10)

    async def cleanup(self) -> None:
        await self.system.tracker_handler.stop()
