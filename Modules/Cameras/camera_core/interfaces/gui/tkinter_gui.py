#!/usr/bin/env python3
"""
Menu-based tkinter GUI for camera system.

Layout:
- Top: Menu bar (File, View, Controls)
- Middle: Camera previews (full space)
- Bottom: Logger feed
"""

import asyncio
import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext
from typing import Optional, TYPE_CHECKING
import datetime

from .widgets import StatusIndicator

if TYPE_CHECKING:
    from ...camera_system import CameraSystem

logger = logging.getLogger("TkinterGUI")


class TkinterGUI:
    """
    Menu-based camera control GUI.

    Top: Menu bar with File/View/Controls
    Middle: Camera previews (side-by-side)
    Bottom: Logger feed
    """

    def __init__(self, camera_system: 'CameraSystem', args):
        """
        Initialize tkinter GUI.

        Args:
            camera_system: Reference to CameraSystem instance
            args: Command-line arguments with configuration
        """
        self.system = camera_system
        self.args = args
        self.root = tk.Tk()
        self.root.title("Camera System")

        # Calculate window size based on gui_start_minimized setting
        num_cameras = len(camera_system.cameras) if camera_system.cameras else 1
        capture_width = args.width
        capture_height = args.height

        # Window dimensions
        padding = 40
        log_height = 100  # Logger frame height (3 lines + padding)
        menu_height = 25  # Approximate menu bar height

        # Set minimum size to accommodate smallest useful view (about half previous size)
        min_width = 160 * num_cameras if num_cameras > 0 else 200
        min_height = 120 + log_height + menu_height
        self.root.minsize(min_width, min_height)

        # Determine initial window size based on config
        start_minimized = getattr(args, 'gui_start_minimized', True)
        if start_minimized:
            # Start at minimal size (compact mode)
            window_width = min_width
            window_height = min_height
        else:
            # Start at capture resolution (full-size mode)
            window_width = capture_width * num_cameras + padding
            window_height = capture_height + log_height + menu_height + padding

        # Apply window geometry (from master logger) or use calculated size
        if hasattr(args, 'window_geometry') and args.window_geometry:
            self.root.geometry(args.window_geometry)
            logger.info("Applied window geometry from master: %s", args.window_geometry)
        else:
            self.root.geometry(f"{window_width}x{window_height}")

        # Track geometry changes (debounced to avoid spamming parent)
        self.last_geometry = None
        self.geometry_save_task = None

        # Preview state
        self.preview_canvases: list[tk.Canvas] = []
        self.preview_image_refs: list = []  # Keep references to prevent GC

        # Camera toggle state
        self.camera_active_vars: list[tk.BooleanVar] = []
        self.camera_active_menu_items: list = []  # Menu checkboxes for camera toggles

        # Build GUI
        self._create_menu_bar()
        self._create_widgets()

        # Set up window close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        logger.info("GUI initialized")

    def _create_menu_bar(self):
        """Create menu bar with File, View, and Controls menus."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Output Directory", command=self._open_output_dir)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_closing)

        # View menu (camera toggles only)
        self.view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=self.view_menu)
        # Camera toggles will be added dynamically in create_preview_canvases()

        # Controls menu
        controls_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Controls", menu=controls_menu)
        controls_menu.add_command(label="▶ Start Recording", command=self._start_recording)
        controls_menu.add_command(label="⏹ Stop Recording", command=self._stop_recording)
        controls_menu.add_separator()
        controls_menu.add_command(label="📷 Snapshot", command=self._take_snapshot)

        # Store menu references for later updates
        self.file_menu = file_menu
        self.controls_menu = controls_menu

    def _open_output_dir(self):
        """Open output directory in file manager."""
        import subprocess
        import sys
        output_dir = self.args.output_dir
        try:
            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(output_dir)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(output_dir)])
            elif sys.platform == 'win32':
                subprocess.Popen(['explorer', str(output_dir)])
            logger.info("Opened output directory: %s", output_dir)
        except Exception as e:
            logger.error("Failed to open output directory: %s", e)

    def _create_widgets(self):
        """Create GUI widgets with menu bar layout."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.grid(row=0, column=0, sticky='nsew')
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Configure main_frame grid: preview area + log feed (no status bar)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)  # Preview area (most space)
        main_frame.rowconfigure(1, weight=0)  # Log feed (3 lines, fixed)

        # === CAMERA PREVIEWS (top, expandable) ===
        preview_frame = ttk.Frame(main_frame)
        preview_frame.grid(row=0, column=0, sticky='nsew', pady=(0, 5))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        # Container for preview canvases
        self.preview_container = ttk.Frame(preview_frame)
        self.preview_container.grid(row=0, column=0, sticky='nsew')
        preview_frame.rowconfigure(0, weight=1)

        # === LOGGER FEED (bottom, 3 lines) ===
        log_frame = ttk.LabelFrame(main_frame, text="Logger", padding="3")
        log_frame.grid(row=1, column=0, sticky='ew')
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=0)

        # Scrolled text widget for log feed (3 lines high, scrollable)
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=3,
            wrap=tk.WORD,
            font=('TkFixedFont', 8),
            bg='#f5f5f5',
            fg='#333333'
        )
        self.log_text.grid(row=0, column=0, sticky='ew')
        self.log_text.config(state='disabled')  # Read-only

        # Set up logging handler to feed into this widget
        self._setup_log_handler()

    def _setup_log_handler(self):
        """Set up logging handler to feed logs into the GUI text widget."""
        class TextHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
                # Format logs nicely
                self.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                                                   datefmt='%H:%M:%S'))

            def emit(self, record):
                msg = self.format(record) + '\n'
                # Schedule GUI update on main thread
                self.text_widget.after(0, self._append_log, msg)

            def _append_log(self, msg):
                self.text_widget.config(state='normal')
                self.text_widget.insert(tk.END, msg)
                self.text_widget.see(tk.END)  # Auto-scroll
                # Limit buffer to last 500 lines
                lines = int(self.text_widget.index('end-1c').split('.')[0])
                if lines > 500:
                    self.text_widget.delete('1.0', f'{lines-500}.0')
                self.text_widget.config(state='disabled')

        # Add handler to root logger
        text_handler = TextHandler(self.log_text)
        text_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(text_handler)
        self.log_handler = text_handler

    def create_preview_canvases(self):
        """Create preview canvas widgets for detected cameras (side by side)."""
        # Clear existing canvases
        for canvas in self.preview_canvases:
            canvas.destroy()
        self.preview_canvases.clear()
        self.preview_image_refs.clear()
        self.camera_active_vars.clear()

        # Clear existing camera menu items from View menu
        menu_size = self.view_menu.index('end')
        if menu_size is not None:
            # Delete all items
            self.view_menu.delete(0, menu_size)
        self.camera_active_menu_items.clear()

        # Use CAPTURE resolution for canvas size (allows full-res display)
        # The actual preview frames will be scaled to fit canvas dynamically
        capture_width = self.args.width
        capture_height = self.args.height

        # Configure preview_container rows
        self.preview_container.rowconfigure(0, weight=0)  # Label row (fixed)
        self.preview_container.rowconfigure(1, weight=1)  # Canvas row (expandable)

        # Create canvas for each camera (side by side)
        for i in range(len(self.system.cameras)):
            # Configure column to expand equally
            self.preview_container.columnconfigure(i, weight=1)

            # Camera label above canvas
            label = ttk.Label(self.preview_container, text=f"Camera {i}",
                            font=('TkDefaultFont', 10, 'bold'))
            label.grid(row=0, column=i, sticky='w', padx=5, pady=(5, 2))

            # Camera canvas - sized to capture resolution initially, scales with window
            canvas = tk.Canvas(self.preview_container,
                             width=capture_width,
                             height=capture_height,
                             bg='black',
                             highlightthickness=1,
                             highlightbackground='gray')
            canvas.grid(row=1, column=i, sticky='nsew', padx=(0, 5 if i < len(self.system.cameras)-1 else 0))

            self.preview_canvases.append(canvas)
            self.preview_image_refs.append(None)

            # Add camera toggle to View menu (only for detected cameras)
            active_var = tk.BooleanVar(value=True)
            self.view_menu.add_checkbutton(label=f"Camera {i}",
                                          variable=active_var,
                                          command=lambda idx=i, var=active_var:
                                                 self._toggle_camera(idx, var.get()))
            self.camera_active_vars.append(active_var)
            self.camera_active_menu_items.append(active_var)

    def _start_recording(self):
        """Start recording on all cameras."""
        if self.system.recording:
            return

        # Start recording
        session_dir = self.system._ensure_session_dir()
        for cam in self.system.cameras:
            cam.start_recording(session_dir)
        self.system.recording = True

        # Update window title to show recording state
        self.root.title(f"Camera System - ⬤ RECORDING - Session: {self.system.session_label}")

        # Disable camera toggles in View menu during recording (safety)
        for i in range(len(self.system.cameras)):
            self.view_menu.entryconfig(f"Camera {i}", state='disabled')

        logger.info("Recording started")

    def _stop_recording(self):
        """Stop recording on all cameras."""
        if not self.system.recording:
            return

        # Stop recording
        for cam in self.system.cameras:
            cam.stop_recording()
        self.system.recording = False

        # Update window title
        self.root.title("Camera System")

        # Re-enable camera toggles in View menu after recording (safety)
        for i in range(len(self.system.cameras)):
            self.view_menu.entryconfig(f"Camera {i}", state='normal')

        logger.info("Recording stopped")

    def _take_snapshot(self):
        """Take snapshots from all cameras."""
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

        # Brief title update for feedback
        original_title = self.root.title()
        self.root.title(f"Camera System - ✓ Saved {snapshot_count} snapshot(s)")
        self.root.after(2000, lambda: self.root.title(original_title))

    def _toggle_camera(self, camera_idx: int, active: bool):
        """
        Toggle camera active state.

        When inactive:
        - Pauses camera capture/processing (saves ~35-50% CPU per camera)
        - Skips GUI preview updates
        - Shows "Camera Inactive" message on canvas

        Args:
            camera_idx: Camera index
            active: True to activate, False to pause
        """
        if camera_idx >= len(self.system.cameras):
            return

        camera = self.system.cameras[camera_idx]

        # Create async task to pause/resume
        async def toggle_async():
            if active:
                success = await camera.resume_camera()
                if success:
                    logger.info("Camera %d resumed", camera_idx)
                    # Clear canvas so it can show live preview again
                    canvas = self.preview_canvases[camera_idx]
                    canvas.delete("all")
            else:
                success = await camera.pause_camera()
                if success:
                    # Clear canvas and show inactive message
                    canvas = self.preview_canvases[camera_idx]
                    canvas.delete("all")
                    # Get canvas dimensions
                    w = canvas.winfo_width() or self.args.width
                    h = canvas.winfo_height() or self.args.height
                    canvas.create_text(w//2, h//2,
                                      text="Camera Inactive",
                                      fill='gray', font=('TkDefaultFont', 12),
                                      justify='center')
                    logger.info("Camera %d paused (saving CPU)", camera_idx)
                else:
                    # Failed to pause (e.g., during recording) - revert menu checkbox
                    self.camera_active_vars[camera_idx].set(True)
                    logger.warning("Cannot pause camera %d", camera_idx)

        # Schedule in event loop
        import asyncio
        asyncio.create_task(toggle_async())

    def _on_closing(self):
        """Handle window close event."""
        logger.info("GUI close requested")

        # Send final geometry to parent before quitting
        try:
            from logger_core.commands import StatusMessage
            # Get current window geometry
            geometry_str = self.root.geometry()  # Returns "WIDTHxHEIGHT+X+Y"
            parts = geometry_str.replace('+', 'x').replace('-', 'x-').split('x')
            if len(parts) >= 4:
                width = int(parts[0])
                height = int(parts[1])
                x = int(parts[2])
                y = int(parts[3])
                StatusMessage.send("geometry_changed", {
                    "width": width,
                    "height": height,
                    "x": x,
                    "y": y
                })
                logger.debug("Sent final geometry to parent: %dx%d+%d+%d", width, height, x, y)
        except Exception as e:
            logger.debug("Failed to send geometry: %s", e)

        # Always send quitting status to parent process (master logger)
        # This allows master to properly track module state
        try:
            from logger_core.commands import StatusMessage
            StatusMessage.send("quitting", {"reason": "user_closed_window"})
            logger.debug("Sent quitting status to parent")
        except Exception as e:
            logger.debug("Failed to send quitting status: %s", e)

        # Immediately hide the window for instant visual feedback
        try:
            self.root.withdraw()
        except Exception:
            pass

        # Set shutdown flags
        self.system.running = False
        self.system.shutdown_event.set()

        # Quit the tkinter event loop to allow app to exit
        # (cleanup happens asynchronously in the background)
        try:
            self.root.quit()
        except Exception as e:
            logger.debug("Error quitting tkinter: %s", e)

    def update_preview_frames(self):
        """Update preview displays with latest frames."""
        for i, cam in enumerate(self.system.cameras):
            if i < len(self.preview_canvases):
                # SKIP INACTIVE CAMERAS (major CPU savings)
                if not cam.is_active:
                    continue

                frame = cam.update_preview_cache()
                if frame is not None:
                    # Convert frame to PhotoImage
                    from PIL import Image, ImageTk
                    import cv2

                    # Convert BGR to RGB
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(frame_rgb)

                    # Get actual current canvas size (handles window resizing)
                    canvas = self.preview_canvases[i]
                    canvas_width = canvas.winfo_width()
                    canvas_height = canvas.winfo_height()

                    # Only resize if canvas has valid dimensions (> 1 means it's been rendered)
                    if canvas_width > 1 and canvas_height > 1:
                        # Maintain aspect ratio when scaling
                        img_width, img_height = image.size

                        # Calculate scaling factor to fit within canvas while maintaining aspect ratio
                        scale_w = canvas_width / img_width
                        scale_h = canvas_height / img_height
                        scale = min(scale_w, scale_h)  # Use smaller scale to fit within canvas

                        # Calculate new dimensions
                        new_width = int(img_width * scale)
                        new_height = int(img_height * scale)

                        # Resize image maintaining aspect ratio
                        if (new_width, new_height) != image.size:
                            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

                        photo = ImageTk.PhotoImage(image)

                        # Update canvas - center the image (with black bars if needed)
                        canvas.delete("all")
                        canvas.create_image(canvas_width//2, canvas_height//2, anchor='center', image=photo)

                        # Keep reference to prevent garbage collection
                        self.preview_image_refs[i] = photo

    def run(self):
        """Start the GUI main loop."""
        self.root.mainloop()

    def destroy(self):
        """Destroy the GUI window."""
        try:
            self.root.quit()
            self.root.destroy()
        except Exception as e:
            logger.debug("Error destroying GUI: %s", e)
