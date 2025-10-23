
import asyncio
import logging
from typing import TYPE_CHECKING

from Modules.base.modes import BaseGUIMode
from ..interfaces.gui import TkinterGUI
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem


logger = logging.getLogger("GUIMode")


class GUIMode(BaseGUIMode):

    def __init__(self, tracker_system: 'TrackerSystem', enable_commands: bool = False):
        super().__init__(tracker_system, enable_commands)
        self.gaze_tracker = None
        self.tracker_task = None

    def create_gui(self) -> TkinterGUI:
        gui = TkinterGUI(self.system, self.system.args)

        from ..gaze_tracker import GazeTracker

        self.gaze_tracker = GazeTracker(
            self.system.config,
            device_manager=self.system.device_manager,
            stream_handler=self.system.stream_handler,
            frame_processor=self.system.frame_processor,
            recording_manager=self.system.recording_manager,
            display_enabled=False  # GUI displays frames, not OpenCV window
        )

        self.system.gaze_tracker = self.gaze_tracker

        return gui

    def create_command_handler(self, gui: TkinterGUI) -> CommandHandler:
        return CommandHandler(self.system, gui=gui)

    async def on_auto_start_recording(self) -> None:
        await asyncio.sleep(3.0)

        if not self.system.recording_manager.is_recording:
            self.logger.info("Auto-starting recording...")
            await self.system.recording_manager.start_recording()
        else:
            self.logger.info("Recording already started")

    async def on_devices_connected(self) -> None:
        self.tracker_task = asyncio.create_task(self.gaze_tracker.run())

        if self.gui and self.gui.root.winfo_exists():
            self.gui.root.title("Eye Tracker - Connected")

    def create_tasks(self) -> list[asyncio.Task]:
        tasks = super().create_tasks()

        if self.system.initialized:
            self.tracker_task = asyncio.create_task(self.gaze_tracker.run())
            tasks.append(self.tracker_task)

        return tasks

    def update_preview(self) -> None:
        if self.gui and self.gui.root.winfo_exists():
            self.gui.update_preview_frame()

    def get_preview_update_interval(self) -> float:
        return 1.0 / getattr(self.system.args, 'gui_preview_update_hz', 10)

    async def cleanup(self) -> None:
        if self.tracker_task and not self.tracker_task.done():
            self.tracker_task.cancel()
            try:
                await self.tracker_task
            except asyncio.CancelledError:
                pass
