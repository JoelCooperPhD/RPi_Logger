
import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext
from typing import Optional, TYPE_CHECKING
import datetime

from Modules.base import TkinterGUIBase, TkinterMenuBase
from .widgets import StatusIndicator

if TYPE_CHECKING:
    from ...camera_system import CameraSystem
    from logger_core.async_bridge import AsyncBridge

logger = logging.getLogger(__name__)


class TkinterGUI(TkinterGUIBase, TkinterMenuBase):

    def __init__(self, camera_system: 'CameraSystem', args):
        self.system = camera_system
        self.args = args

        # Initialize module-specific attributes before GUI framework
        self.preview_canvases: list[tk.Canvas] = []
        self.preview_image_refs: list = []  # Keep references to prevent GC
        self.camera_active_vars: list[tk.BooleanVar] = []
        self.camera_active_menu_items: list = []  # Menu checkboxes for camera toggles
        self.recording_indicator_vars: list[tk.StringVar] = []  # Recording status text vars
        self.async_bridge: Optional['AsyncBridge'] = None

        # Use template method for GUI initialization
        self.initialize_gui_framework(
            title="Camera System",
            default_width=800,
            default_height=600
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
        content_frame = self.create_standard_layout(logger_height=3, content_title="Camera Previews")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        self.preview_container = ttk.Frame(content_frame)
        self.preview_container.grid(row=0, column=0, sticky='nsew')

    def create_preview_canvases(self):
        for canvas in self.preview_canvases:
            canvas.destroy()
        self.preview_canvases.clear()
        self.preview_image_refs.clear()
        self.camera_active_vars.clear()
        self.recording_indicator_vars.clear()

        menu_size = self.sources_menu.index('end')
        if menu_size is not None:
            self.sources_menu.delete(0, menu_size)
        self.camera_active_menu_items.clear()

        preview_width = self.args.preview_width
        preview_height = self.args.preview_height

        self.preview_container.rowconfigure(0, weight=0)  # Label row (fixed)
        self.preview_container.rowconfigure(1, weight=1)  # Canvas row (expandable)

        for i in range(len(self.system.cameras)):
            self.preview_container.columnconfigure(i, weight=1)

            # Create header frame for camera label + recording indicator
            header_frame = ttk.Frame(self.preview_container)
            header_frame.grid(row=0, column=i, sticky='w', padx=5, pady=(5, 2))

            # Camera label
            label = ttk.Label(header_frame, text=f"Camera {i}")
            label.pack(side='left')

            # Recording indicator (controlled by StringVar)
            rec_var = tk.StringVar(value="")
            rec_label = tk.Label(header_frame, textvariable=rec_var, fg='red', font=('TkDefaultFont', 9, 'bold'))
            rec_label.pack(side='left')
            self.recording_indicator_vars.append(rec_var)
            logger.info(f"Created recording indicator for camera {i}, label exists: {rec_label is not None}")

            canvas = tk.Canvas(self.preview_container,
                             width=preview_width,
                             height=preview_height,
                             bg='black',
                             highlightthickness=1,
                             highlightbackground='gray')
            canvas.grid(row=1, column=i, sticky='nsew', padx=(0, 5 if i < len(self.system.cameras)-1 else 0))

            self.preview_canvases.append(canvas)
            self.preview_image_refs.append(None)

            active_var = tk.BooleanVar(value=True)
            self.add_source_toggle(
                label=f"Camera {i}",
                variable=active_var,
                command=lambda idx=i, var=active_var: self._toggle_camera(idx, var.get())
            )
            self.camera_active_vars.append(active_var)
            self.camera_active_menu_items.append(active_var)

    def _start_recording(self):
        if self.system.recording:
            return

        if not self.async_bridge:
            self._handle_recording_error("Async bridge not configured; cannot start recording")
            return

        future = self.async_bridge.run_coroutine(self.system.start_recording())

        def _on_complete(fut):
            try:
                success = fut.result()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("GUI start recording failed: %s", exc, exc_info=True)

                def _error_callback():
                    self._handle_recording_error("Failed to start recording")

                self.async_bridge.call_in_gui(_error_callback)
                return

            def _apply_callback():
                if success and self.system.recording:
                    self._apply_recording_ui_state(True)
                    logger.info("Recording started")
                else:
                    self._handle_recording_error("Unable to start recording")

            self.async_bridge.call_in_gui(_apply_callback)

        future.add_done_callback(_on_complete)

    def _stop_recording(self):
        if not self.system.recording:
            return

        if not self.async_bridge:
            self._handle_recording_error("Async bridge not configured; cannot stop recording")
            return

        future = self.async_bridge.run_coroutine(self.system.stop_recording())

        def _on_complete(fut):
            try:
                success = fut.result()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("GUI stop recording failed: %s", exc, exc_info=True)

                def _error_callback():
                    self._handle_recording_error("Failed to stop recording")

                self.async_bridge.call_in_gui(_error_callback)
                return

            def _apply_callback():
                if success:
                    self._apply_recording_ui_state(False)
                    logger.info("Recording stopped")
                else:
                    self._handle_recording_error("Unable to stop recording")

            self.async_bridge.call_in_gui(_apply_callback)

        future.add_done_callback(_on_complete)

    def _take_snapshot(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self.system._ensure_session_dir()
        snapshot_count = 0

        for i, cam in enumerate(self.system.cameras):
            frame = cam.update_preview_cache()
            if frame is not None:
                import cv2
                filename = session_dir / f"snapshot_cam{i}_{ts}.jpg"
                cv2.imwrite(str(filename), frame)
                snapshot_count += 1
                logger.info("Saved snapshot: %s", filename)

        original_title = self.root.title()
        self.root.title(f"Camera System - ✓ Saved {snapshot_count} snapshot(s)")
        self.root.after(2000, lambda: self.root.title(original_title))

    def _toggle_camera(self, camera_idx: int, active: bool):
        if camera_idx >= len(self.system.cameras):
            return

        bridge = self.async_bridge
        if bridge is None:
            logger.error("Async bridge not configured; cannot toggle camera %d", camera_idx)
            return

        camera = self.system.cameras[camera_idx]

        async def toggle_async():
            try:
                if active:
                    success = await camera.resume_camera()
                    if success:
                        logger.info("Camera %d resumed", camera_idx)
                        bridge.call_in_gui(lambda: self._clear_camera_canvas(camera_idx))
                    else:
                        bridge.call_in_gui(lambda: self._restore_toggle_state(camera_idx, False))
                else:
                    success = await camera.pause_camera()
                    if success:
                        logger.info("Camera %d paused (saving CPU)", camera_idx)
                        bridge.call_in_gui(lambda: self._show_camera_inactive(camera_idx))
                    else:
                        bridge.call_in_gui(lambda: self._restore_toggle_state(camera_idx, True))
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Toggle camera %d failed: %s", camera_idx, exc, exc_info=True)
                bridge.call_in_gui(
                    lambda: self._restore_toggle_state(camera_idx, camera.is_active)
                )

        bridge.run_coroutine(toggle_async())

    def _apply_recording_ui_state(self, is_recording: bool):
        if is_recording:
            session_label = getattr(self.system, 'session_label', '')
            title = "Camera System - ⬤ RECORDING"
            if session_label:
                title += f" - Session: {session_label}"
            self.root.title(title)
            for rec_var in self.recording_indicator_vars:
                rec_var.set(" RECORDING")
            self.enable_sources_menu(False)
        else:
            self.root.title("Camera System")
            for rec_var in self.recording_indicator_vars:
                rec_var.set("")
            self.enable_sources_menu(True)

    def _handle_recording_error(self, message: str):
        logger.error(message)
        self.root.title(f"Camera System - ⚠ {message}")
        self.enable_sources_menu(not self.system.recording)
        # Re-apply correct UI state after short delay in case the system state changes
        self.root.after(2000, lambda: self._apply_recording_ui_state(self.system.recording))

    def _clear_camera_canvas(self, camera_idx: int):
        if camera_idx < len(self.preview_canvases):
            canvas = self.preview_canvases[camera_idx]
            canvas.delete("all")

    def _show_camera_inactive(self, camera_idx: int):
        if camera_idx < len(self.preview_canvases):
            canvas = self.preview_canvases[camera_idx]
            canvas.delete("all")
            w = canvas.winfo_width() or self.args.preview_width
            h = canvas.winfo_height() or self.args.preview_height
            canvas.create_text(
                w // 2,
                h // 2,
                text="Camera Inactive",
                fill='gray',
                justify='center'
            )

    def _restore_toggle_state(self, camera_idx: int, should_be_active: bool):
        if camera_idx < len(self.camera_active_vars):
            self.camera_active_vars[camera_idx].set(should_be_active)

    def save_window_geometry_to_config(self):
        from pathlib import Path
        from Modules.base import gui_utils
        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)


    def update_preview_frames(self):
        if not self.system.initialized:
            self._show_waiting_message()
            return

        for i, cam in enumerate(self.system.cameras):
            if i < len(self.preview_canvases):
                if not cam.is_active:
                    continue

                frame = cam.update_preview_cache()
                if frame is not None:
                    from PIL import Image, ImageTk
                    import cv2

                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(frame_rgb)

                    preview_width = self.args.preview_width
                    preview_height = self.args.preview_height

                    if image.size != (preview_width, preview_height):
                        image = image.resize((preview_width, preview_height), Image.Resampling.BILINEAR)

                    photo = ImageTk.PhotoImage(image)

                    canvas = self.preview_canvases[i]
                    canvas_width = canvas.winfo_width()
                    canvas_height = canvas.winfo_height()

                    canvas.delete("all")
                    canvas.create_image(canvas_width//2, canvas_height//2, anchor='center', image=photo)

                    self.preview_image_refs[i] = photo

    def _show_waiting_message(self):
        for canvas in self.preview_canvases:
            canvas.delete("all")

        if not self.preview_canvases:
            self.preview_container.columnconfigure(0, weight=1)
            canvas = tk.Canvas(self.preview_container,
                             bg='black',
                             highlightthickness=1,
                             highlightbackground='gray')
            canvas.grid(row=1, column=0, sticky='nsew')
            self.preview_canvases.append(canvas)

        if self.preview_canvases:
            canvas = self.preview_canvases[0]
            canvas_width = canvas.winfo_width()
            canvas_height = canvas.winfo_height()

            canvas.create_text(
                canvas_width // 2,
                canvas_height // 2,
                text="Waiting for cameras...\n\nChecking every 3 seconds",
                fill="white",
                justify='center'
            )

    def run(self):
        self.root.mainloop()

    def sync_recording_state(self):
        """Called by CommandHandler to sync GUI state after recording state changes"""
        is_recording = self.system.recording

        if is_recording:
            # Show recording indicators
            for rec_var in self.recording_indicator_vars:
                rec_var.set(" RECORDING")
            self.root.title(f"Camera System - ⬤ RECORDING - Session: {self.system.session_label}")
            logger.info("GUI synced: Recording indicators shown")
        else:
            # Hide recording indicators
            for rec_var in self.recording_indicator_vars:
                rec_var.set("")
            self.root.title("Camera System")
            logger.info("GUI synced: Recording indicators hidden")

    def destroy(self):
        try:
            self.root.quit()
            self.root.destroy()
        except Exception as e:
            logger.debug("Error destroying GUI: %s", e)
