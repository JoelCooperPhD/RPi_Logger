
import asyncio
import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext
from typing import Optional, TYPE_CHECKING
import datetime

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.ui.theme.styles import Theme
from rpi_logger.core.ui.theme.colors import Colors
from rpi_logger.modules.base import TkinterGUIBase, TkinterMenuBase

if TYPE_CHECKING:
    from ...tracker_system import TrackerSystem

logger = get_module_logger("EyeTracker.TkinterGUI")


class TkinterGUI(TkinterGUIBase, TkinterMenuBase):

    def __init__(self, tracker_system: 'TrackerSystem', args):
        self.system = tracker_system
        self.args = args

        self.preview_width = getattr(args, 'preview_width', 640) or 640
        preview_height = getattr(args, 'preview_height', None)
        if not preview_height:
            preview_height = int(self.preview_width * 3 / 4)
        self.preview_height = preview_height

        # Initialize module-specific attributes before GUI framework
        self.preview_canvas: Optional[tk.Canvas] = None
        self.preview_image_ref = None  # Keep reference to prevent GC

        # Use template method for GUI initialization
        self.initialize_gui_framework(
            title="Eye Tracker",
            default_width=800,
            default_height=600,
            menu_bar_kwargs={'include_sources': False}  # No Sources menu needed
        )

    def populate_module_menus(self):
        self.file_menu.insert_command(
            0,
            label="📷 Snapshot",
            command=self._take_snapshot
        )
        self.file_menu.insert_separator(1)

    def on_start_recording(self):
        self._start_recording()

    def on_stop_recording(self):
        self._stop_recording()

    def _create_widgets(self):
        content_frame = self.create_standard_layout(logger_height=4, content_title="Eye Tracker")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=0)  # Label row (fixed)
        content_frame.rowconfigure(1, weight=1)  # Canvas row (expandable)

        self.preview_frame = content_frame

        label = ttk.Label(content_frame, text="Scene Camera (with Gaze Overlay)")
        label.grid(row=0, column=0, sticky='w', padx=5, pady=(5, 2))

        self.preview_canvas = tk.Canvas(
            content_frame,
            width=self.preview_width,
            height=self.preview_height,
            bg=Colors.BG_CANVAS,
            highlightthickness=1,
            highlightbackground=Colors.BORDER
        )
        self.preview_canvas.grid(row=1, column=0, sticky='nsew')

    def _start_recording(self):
        async def start_async():
            if self.system.recording:
                logger.warning("Already recording")
                return

            started = await self.system.start_recording()
            if not started:
                logger.error("Failed to start recording")
                return

            experiment_label = self.system.recording_manager.current_experiment_label or "unknown"
            self.root.title(f"Eye Tracker - ⬤ RECORDING - {experiment_label}")

            logger.info("Recording started")

        asyncio.create_task(start_async())

    def _stop_recording(self):
        async def stop_async():
            if not self.system.recording:
                logger.warning("Not recording")
                return

            stopped = await self.system.stop_recording()
            if not stopped:
                logger.error("Failed to stop recording")
                return

            self.root.title("Eye Tracker")

            logger.info("Recording stopped")

        asyncio.create_task(stop_async())

    def _take_snapshot(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self.system.session_dir

        latest_frame = self.system.tracker_handler.get_display_frame()

        if latest_frame is not None:
            import cv2
            filename = session_dir / f"snapshot_eyetracker_{ts}.jpg"
            cv2.imwrite(str(filename), latest_frame.copy())
            logger.info("Saved snapshot: %s", filename)

            original_title = self.root.title()
            self.root.title(f"Eye Tracker - ✓ Saved snapshot")
            self.root.after(2000, lambda: self.root.title(original_title))
        else:
            logger.warning("No frame available for snapshot")

    def save_window_geometry_to_config(self):
        from pathlib import Path
        from rpi_logger.modules.base import gui_utils
        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)


    def update_preview_frame(self):
        if not self.preview_canvas:
            return

        if not self.system.initialized:
            self._show_waiting_message()
            return

        frame = self.system.tracker_handler.get_display_frame()
        if frame is None:
            return

        if frame is not None:
            from PIL import Image
            import cv2
            import io

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(frame_rgb)
            # Use native Tk PhotoImage with PPM to avoid PIL ImageTk issues
            ppm_data = io.BytesIO()
            image.save(ppm_data, format="PPM")
            photo = tk.PhotoImage(data=ppm_data.getvalue())

            canvas_width = self.preview_canvas.winfo_width() or self.preview_width
            canvas_height = self.preview_canvas.winfo_height() or self.preview_height

            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(
                canvas_width // 2,
                canvas_height // 2,
                anchor='center',
                image=photo
            )

            # Keep reference to prevent garbage collection
            self.preview_image_ref = photo

    def _show_waiting_message(self):
        if not self.preview_canvas:
            return

        self.preview_canvas.delete("all")

        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()

        self.preview_canvas.create_text(
            canvas_width // 2,
            canvas_height // 2,
            text="Waiting for eye tracker device...\n\nChecking every 3 seconds",
            fill=Colors.FG_PRIMARY,
            justify='center'
        )

    def run(self):
        self.root.mainloop()

    def destroy(self):
        try:
            self.root.quit()
            self.root.destroy()
        except Exception as e:
            logger.debug("Error destroying GUI: %s", e)
