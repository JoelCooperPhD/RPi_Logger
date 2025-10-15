#!/usr/bin/env python3
"""
Menu-based tkinter GUI for eye tracker system.

Layout:
- Top: Menu bar (File, View, Controls)
- Middle: Scene camera preview with gaze overlay (full space)
- Bottom: Logger feed
"""

import asyncio
import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext
from typing import Optional, TYPE_CHECKING
import datetime

if TYPE_CHECKING:
    from ...tracker_system import TrackerSystem

logger = logging.getLogger("TkinterGUI")


class TkinterGUI:
    """
    Menu-based eye tracker GUI.

    Top: Menu bar with File/View/Controls
    Middle: Scene camera preview with gaze overlay
    Bottom: Logger feed
    """

    def __init__(self, tracker_system: 'TrackerSystem', args):
        """
        Initialize tkinter GUI.

        Args:
            tracker_system: Reference to TrackerSystem instance
            args: Command-line arguments with configuration
        """
        self.system = tracker_system
        self.args = args
        self.root = tk.Tk()
        self.root.title("Eye Tracker")

        # Calculate window size based on gui_start_minimized setting
        capture_width = args.width if hasattr(args, 'width') else 1280
        capture_height = args.height if hasattr(args, 'height') else 720

        # Window dimensions
        padding = 40
        log_height = 100  # Logger frame height (3 lines + padding)
        menu_height = 25  # Approximate menu bar height

        # Set minimum size
        min_width = 320
        min_height = 240 + log_height + menu_height
        self.root.minsize(min_width, min_height)

        # Determine initial window size based on config
        start_minimized = getattr(args, 'gui_start_minimized', True)
        if start_minimized:
            # Start at minimal size (compact mode)
            window_width = min_width
            window_height = min_height
        else:
            # Start at capture resolution (full-size mode)
            window_width = capture_width + padding
            window_height = capture_height + log_height + menu_height + padding

        # Apply window geometry (from master logger) or use calculated size
        if hasattr(args, 'window_geometry') and args.window_geometry:
            self.root.geometry(args.window_geometry)
            logger.info("Applied window geometry from master: %s", args.window_geometry)
        else:
            self.root.geometry(f"{window_width}x{window_height}")

        # Preview state
        self.preview_canvas: Optional[tk.Canvas] = None
        self.preview_image_ref = None  # Keep reference to prevent GC

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

        # View menu (for future features)
        self.view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=self.view_menu)
        # Placeholder for future features

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

        # Configure main_frame grid: preview area + log feed
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)  # Preview area (most space)
        main_frame.rowconfigure(1, weight=0)  # Log feed (3 lines, fixed)

        # === SCENE CAMERA PREVIEW (top, expandable) ===
        preview_frame = ttk.Frame(main_frame)
        preview_frame.grid(row=0, column=0, sticky='nsew', pady=(0, 5))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        # Scene camera label
        label = ttk.Label(preview_frame, text="Scene Camera (with Gaze Overlay)",
                        font=('TkDefaultFont', 10, 'bold'))
        label.grid(row=0, column=0, sticky='w', padx=5, pady=(5, 2))

        # Scene camera canvas - sized to capture resolution initially, scales with window
        self.preview_canvas = tk.Canvas(preview_frame,
                         width=self.args.width if hasattr(self.args, 'width') else 1280,
                         height=self.args.height if hasattr(self.args, 'height') else 720,
                         bg='black',
                         highlightthickness=1,
                         highlightbackground='gray')
        self.preview_canvas.grid(row=1, column=0, sticky='nsew')
        preview_frame.rowconfigure(1, weight=1)

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

    def _start_recording(self):
        """Start recording."""
        # Create async task to start recording
        async def start_async():
            if self.system.recording_manager.is_recording:
                logger.warning("Already recording")
                return

            await self.system.recording_manager.start_recording()

            # Update window title to show recording state
            experiment_label = self.system.recording_manager.current_experiment_label or "unknown"
            self.root.title(f"Eye Tracker - ⬤ RECORDING - {experiment_label}")

            logger.info("Recording started")

        # Schedule in event loop
        asyncio.create_task(start_async())

    def _stop_recording(self):
        """Stop recording."""
        # Create async task to stop recording
        async def stop_async():
            if not self.system.recording_manager.is_recording:
                logger.warning("Not recording")
                return

            await self.system.recording_manager.stop_recording()

            # Update window title
            self.root.title("Eye Tracker")

            logger.info("Recording stopped")

        # Schedule in event loop
        asyncio.create_task(stop_async())

    def _take_snapshot(self):
        """Take snapshot from eye tracker."""
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self.system.session_dir

        # Get latest processed frame from frame_processor
        latest_frame = self.system.frame_processor._latest_processed_frame if hasattr(self.system.frame_processor, '_latest_processed_frame') else None

        if latest_frame is not None:
            import cv2
            filename = session_dir / f"snapshot_eyetracker_{ts}.jpg"
            cv2.imwrite(str(filename), latest_frame)
            logger.info("Saved snapshot: %s", filename)

            # Brief title update for feedback
            original_title = self.root.title()
            self.root.title(f"Eye Tracker - ✓ Saved snapshot")
            self.root.after(2000, lambda: self.root.title(original_title))
        else:
            logger.warning("No frame available for snapshot")

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

    def update_preview_frame(self):
        """Update preview display with latest frame."""
        if not self.preview_canvas:
            return

        # Get the GazeTracker instance from the system
        # The frame_processor already adds the overlays, so we just need to display it
        if not hasattr(self.system, 'gaze_tracker') or self.system.gaze_tracker is None:
            return

        # Get latest processed frame with overlays
        tracker = self.system.gaze_tracker
        if not hasattr(tracker, '_latest_display_frame') or tracker._latest_display_frame is None:
            return

        frame = tracker._latest_display_frame

        if frame is not None:
            # Convert frame to PhotoImage
            from PIL import Image, ImageTk
            import cv2

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(frame_rgb)

            # Get actual current canvas size (handles window resizing)
            canvas_width = self.preview_canvas.winfo_width()
            canvas_height = self.preview_canvas.winfo_height()

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
                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(canvas_width//2, canvas_height//2, anchor='center', image=photo)

                # Keep reference to prevent garbage collection
                self.preview_image_ref = photo

                # Store processed frame for snapshots
                self.system.frame_processor._latest_processed_frame = frame

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
