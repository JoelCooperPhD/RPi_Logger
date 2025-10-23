
import asyncio
import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext
from typing import Optional, TYPE_CHECKING
import datetime

from Modules.base import TkinterGUIBase, TkinterMenuBase

if TYPE_CHECKING:
    from ...tracker_system import TrackerSystem

logger = logging.getLogger("TkinterGUI")


class TkinterGUI(TkinterGUIBase, TkinterMenuBase):

    def __init__(self, tracker_system: 'TrackerSystem', args):
        self.system = tracker_system
        self.args = args
        self.root = tk.Tk()
        self.root.title("Eye Tracker")

        self.initialize_window_geometry(800, 600)

        self.preview_canvas: Optional[tk.Canvas] = None
        self.preview_image_ref = None  # Keep reference to prevent GC

        self.create_menu_bar(include_sources=False)  # From TkinterMenuBase (no Sources menu needed)
        self._create_widgets()


        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        logger.info("GUI initialized")

    def populate_module_menus(self):
        self.add_recording_action("📷 Snapshot", self._take_snapshot, separator_before=True)

    def on_start_recording(self):
        self._start_recording()

    def on_stop_recording(self):
        self._stop_recording()

    def _create_widgets(self):
        content_frame = self.create_standard_layout(logger_height=3, content_title="Eye Tracker")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=0)  # Label row (fixed)
        content_frame.rowconfigure(1, weight=1)  # Canvas row (expandable)

        self.preview_frame = content_frame

        label = ttk.Label(content_frame, text="Scene Camera (with Gaze Overlay)",
                        font=('TkDefaultFont', 10, 'bold'))
        label.grid(row=0, column=0, sticky='w', padx=5, pady=(5, 2))

        self.preview_canvas = tk.Canvas(content_frame,
                         width=self.args.width if hasattr(self.args, 'width') else 1280,
                         height=self.args.height if hasattr(self.args, 'height') else 720,
                         bg='black',
                         highlightthickness=1,
                         highlightbackground='gray')
        self.preview_canvas.grid(row=1, column=0, sticky='nsew')

    def _start_recording(self):
        async def start_async():
            if self.system.recording_manager.is_recording:
                logger.warning("Already recording")
                return

            await self.system.recording_manager.start_recording()

            experiment_label = self.system.recording_manager.current_experiment_label or "unknown"
            self.root.title(f"Eye Tracker - ⬤ RECORDING - {experiment_label}")

            logger.info("Recording started")

        asyncio.create_task(start_async())

    def _stop_recording(self):
        async def stop_async():
            if not self.system.recording_manager.is_recording:
                logger.warning("Not recording")
                return

            await self.system.recording_manager.stop_recording()

            self.root.title("Eye Tracker")

            logger.info("Recording stopped")

        asyncio.create_task(stop_async())

    def _take_snapshot(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self.system.session_dir

        latest_frame = self.system.frame_processor._latest_processed_frame if hasattr(self.system.frame_processor, '_latest_processed_frame') else None

        if latest_frame is not None:
            import cv2
            filename = session_dir / f"snapshot_eyetracker_{ts}.jpg"
            cv2.imwrite(str(filename), latest_frame)
            logger.info("Saved snapshot: %s", filename)

            original_title = self.root.title()
            self.root.title(f"Eye Tracker - ✓ Saved snapshot")
            self.root.after(2000, lambda: self.root.title(original_title))
        else:
            logger.warning("No frame available for snapshot")

    def _on_closing(self):
        self.handle_window_close()

    def save_window_geometry_to_config(self):
        from pathlib import Path
        from Modules.base import gui_utils
        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)


    def update_preview_frame(self):
        if not self.preview_canvas:
            return

        if not self.system.initialized:
            self._show_waiting_message()
            return

        if not hasattr(self.system, 'gaze_tracker') or self.system.gaze_tracker is None:
            self._show_waiting_message()
            return

        tracker = self.system.gaze_tracker
        if not hasattr(tracker, '_latest_display_frame') or tracker._latest_display_frame is None:
            return

        frame = tracker._latest_display_frame

        if frame is not None:
            from PIL import Image, ImageTk
            import cv2

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(frame_rgb)

            canvas_width = self.preview_canvas.winfo_width()
            canvas_height = self.preview_canvas.winfo_height()

            if canvas_width > 1 and canvas_height > 1:
                img_width, img_height = image.size

                scale_w = canvas_width / img_width
                scale_h = canvas_height / img_height
                scale = min(scale_w, scale_h)  # Use smaller scale to fit within canvas

                new_width = int(img_width * scale)
                new_height = int(img_height * scale)

                if (new_width, new_height) != image.size:
                    image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

                photo = ImageTk.PhotoImage(image)

                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(canvas_width//2, canvas_height//2, anchor='center', image=photo)

                # Keep reference to prevent garbage collection
                self.preview_image_ref = photo

                self.system.frame_processor._latest_processed_frame = frame

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
            fill="white",
            font=('TkDefaultFont', 14),
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
