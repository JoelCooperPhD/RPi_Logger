"""Single-camera view for Cameras module.

Each Cameras instance displays exactly one camera. This view provides
the preview canvas, status display, metrics, and settings configuration.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.app.widgets.camera_settings_window import (
    CameraSettingsWindow,
    DEFAULT_SETTINGS,
)

try:
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None


def _format_fps(value: Any) -> str:
    """Format a FPS value for display."""
    if value is None:
        return "  --"
    try:
        return f"{float(value):5.1f}"
    except (ValueError, TypeError):
        return "  --"


def _fps_color(actual: Any, target: Any) -> Optional[str]:
    """Get color based on how close actual FPS is to target."""
    if not HAS_THEME or Colors is None:
        return None
    try:
        if actual is not None and target is not None and float(target) > 0:
            pct = (float(actual) / float(target)) * 100
            if pct >= 95:
                return Colors.SUCCESS   # Green - good
            elif pct >= 80:
                return Colors.WARNING   # Orange - warning
            else:
                return Colors.ERROR     # Red - bad
    except (ValueError, TypeError):
        pass
    return Colors.FG_PRIMARY


class CameraView:
    """Single-camera view with preview canvas, status, metrics, and settings."""

    def __init__(self, stub_view: Any = None, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._stub_view = stub_view
        self._root = getattr(stub_view, "root", None)
        self._ui_thread = threading.current_thread()

        # UI elements
        self._canvas = None
        self._photo = None
        self._status_label = None
        self._recording_indicator = None
        self._has_ui = False

        # Metrics display elements (IO stub area)
        self._metrics_fields: Dict[str, Any] = {}  # StringVars
        self._metrics_labels: Dict[str, Any] = {}  # Labels for color

        # Settings window
        self._settings_window: Optional[CameraSettingsWindow] = None
        self._settings_toggle_var: Optional[Any] = None
        self._settings_menu: Any = None

        # Handlers
        self._config_handler: Optional[Callable[[str, Dict[str, str]], None]] = None
        self._control_change_handler: Optional[Callable[[str, str, Any], None]] = None
        self._reprobe_handler: Optional[Callable[[str], None]] = None

        # State
        self._camera_id: Optional[str] = None
        self._camera_name: Optional[str] = None
        self._is_recording: bool = False
        self._frame_count: int = 0
        self._camera_settings: Dict[str, str] = dict(DEFAULT_SETTINGS)
        self._camera_options: Dict[str, List[str]] = {}

    def attach(self) -> None:
        """Mount the camera view inside the stub view frame."""
        if not self._stub_view:
            self._logger.info("Camera view running headless (no stub view)")
            return

        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:
            self._logger.warning("Tk unavailable for camera view: %s", exc)
            return

        self._ui_thread = threading.current_thread()

        def builder(parent):
            self._build_layout(parent, tk)

        self._stub_view.build_stub_content(builder)

        # Install metrics in the IO stub content area
        self._install_metrics_display(tk, ttk)

        # Install settings window and menu
        self._install_settings_window(tk)
        self._install_settings_menu(tk)

        self._has_ui = True
        self._logger.info("Camera view attached")

    def bind_handlers(
        self,
        *,
        apply_config: Optional[Callable[[str, Dict[str, str]], None]] = None,
        control_change: Optional[Callable[[str, str, Any], None]] = None,
        reprobe: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Bind handler callbacks for settings changes."""
        self._config_handler = apply_config
        self._control_change_handler = control_change
        self._reprobe_handler = reprobe

    def _build_layout(self, parent, tk) -> None:
        """Build single camera view layout."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        # Main container
        bg_color = Colors.BG_FRAME if HAS_THEME and Colors else "black"
        fg_color = Colors.FG_PRIMARY if HAS_THEME and Colors else "white"

        container = tk.Frame(parent, bg=bg_color)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        # Canvas for video preview
        self._canvas = tk.Canvas(container, bg="black", highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")

        # Status bar at bottom
        status_frame = tk.Frame(container, bg=bg_color)
        status_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=2)
        status_frame.columnconfigure(1, weight=1)

        # Recording indicator (red dot when recording)
        self._recording_indicator = tk.Label(
            status_frame, text="\u25cf", fg="gray", bg=bg_color,
            font=("", 12)
        )
        self._recording_indicator.grid(row=0, column=0, padx=(0, 4))

        # Status label
        self._status_label = tk.Label(
            status_frame, text="Waiting for camera...",
            anchor="w", bg=bg_color, fg=fg_color
        )
        self._status_label.grid(row=0, column=1, sticky="w")

    def _install_metrics_display(self, tk, ttk) -> None:
        """Install the capture stats display into the IO stub content area."""
        builder = getattr(self._stub_view, "build_io_stub_content", None)
        if not callable(builder):
            return

        # Define the fields to show
        fields = [
            ("cap_tgt", "Cap In/Tgt"),
            ("rec_tgt", "Rec Out/Tgt"),
            ("disp_tgt", "Disp/Tgt"),
        ]

        # Initialize StringVars
        for key, _ in fields:
            self._metrics_fields[key] = tk.StringVar(master=self._root, value="  -- /   --")

        def _builder(frame) -> None:
            bg = Colors.BG_FRAME if HAS_THEME and Colors else None
            fg1 = Colors.FG_SECONDARY if HAS_THEME and Colors else None
            fg2 = Colors.FG_PRIMARY if HAS_THEME and Colors else None

            if HAS_THEME and Colors:
                container = tk.Frame(frame, bg=bg)
            else:
                container = ttk.Frame(frame)
            container.grid(row=0, column=0, sticky="ew")
            for idx in range(len(fields)):
                container.columnconfigure(idx, weight=1, uniform="iofields")

            for col, (key, label_text) in enumerate(fields):
                if HAS_THEME and Colors:
                    name = tk.Label(
                        container, text=label_text, anchor="center",
                        bg=bg, fg=fg1
                    )
                    val = tk.Label(
                        container, textvariable=self._metrics_fields[key], anchor="center",
                        bg=bg, fg=fg2, font=("TkFixedFont", 9)
                    )
                else:
                    name = ttk.Label(container, text=label_text, anchor="center")
                    val = ttk.Label(container, textvariable=self._metrics_fields[key], anchor="center")
                    try:
                        val.configure(font=("TkFixedFont", 9))
                    except Exception:
                        pass
                name.grid(row=0, column=col, sticky="ew", padx=2)
                val.grid(row=1, column=col, sticky="ew", padx=2)
                self._metrics_labels[key] = val

        try:
            builder(_builder)
        except Exception:
            self._logger.debug("IO stub content build failed", exc_info=True)

    def _install_settings_window(self, tk) -> None:
        """Create the settings window (shown via menu)."""
        if self._settings_toggle_var is None:
            self._settings_toggle_var = tk.BooleanVar(master=self._root, value=False)

        if self._settings_window is None:
            self._settings_window = CameraSettingsWindow(
                self._root,
                logger=self._logger,
                on_apply_resolution=self._on_apply_config,
                on_control_change=self._on_control_change,
                on_reprobe=self._on_reprobe,
            )
            self._settings_window.bind_toggle_var(self._settings_toggle_var)

    def _install_settings_menu(self, tk) -> None:
        """Add Configure menu item to the stub view's menu."""
        if self._settings_menu:
            return

        menu = None

        # Try add_menu helper first
        add_menu = getattr(self._stub_view, "add_menu", None)
        if callable(add_menu):
            try:
                menu = add_menu("Controls")
            except Exception:
                menu = None

        # Fall back to creating menu on menubar
        if menu is None:
            menubar = getattr(self._stub_view, "menubar", None)
            if menubar is not None:
                try:
                    menu = tk.Menu(menubar, tearoff=0)
                    menubar.add_cascade(label="Controls", menu=menu)
                except Exception:
                    menu = None

        # Last resort: try module_menu attribute
        if menu is None:
            menu = getattr(self._stub_view, "module_menu", None)

        if menu is None:
            self._logger.debug("Settings menu unavailable; skipping menu wiring")
            return

        self._settings_menu = menu

        if self._settings_toggle_var is not None:
            menu.add_checkbutton(
                label="Configure",
                variable=self._settings_toggle_var,
                command=self._toggle_settings_window,
            )

        menu.add_separator()
        menu.add_command(
            label="Reprobe Camera",
            command=lambda: self._on_reprobe(self._camera_id),
        )

    def _toggle_settings_window(self) -> None:
        """Toggle visibility of the settings window."""
        if not self._settings_window or not self._settings_toggle_var:
            return

        visible = bool(self._settings_toggle_var.get())
        if visible:
            # Update settings window with current camera
            if self._camera_id:
                self._settings_window.set_camera_settings(self._camera_id, self._camera_settings)
                self._settings_window.set_active_camera(self._camera_id)
            self._settings_window.show()
        else:
            self._settings_window.hide()

    def _on_apply_config(self, camera_id: str, settings: Dict[str, str]) -> None:
        """Handle config apply from settings window."""
        self._logger.info("_on_apply_config called: camera_id=%s, settings=%s", camera_id, settings)
        if not camera_id:
            self.set_status("No camera selected")
            return

        self._camera_settings.update(settings)

        if self._config_handler:
            self._logger.info("Calling config handler")
            try:
                self._config_handler(camera_id, settings)
                self.set_status(f"Config applied")
            except Exception:
                self._logger.debug("Config handler failed", exc_info=True)
        else:
            self._logger.warning("No config handler registered")

    def _on_control_change(self, camera_id: str, control_name: str, value: Any) -> None:
        """Handle camera control change from settings window."""
        if not self._control_change_handler:
            self._logger.debug("No control change handler registered")
            return
        try:
            self._control_change_handler(camera_id, control_name, value)
        except Exception:
            self._logger.debug("Control change handler failed", exc_info=True)

    def _on_reprobe(self, camera_id: Optional[str] = None) -> None:
        """Handle reprobe request."""
        target = camera_id or self._camera_id
        if not target:
            self.set_status("No camera to reprobe")
            return

        if self._reprobe_handler:
            try:
                self._reprobe_handler(target)
                self.set_status(f"Reprobing camera...")
            except Exception:
                self._logger.debug("Reprobe handler failed", exc_info=True)

    # ------------------------------------------------------------------ Public API

    def set_camera_info(self, name: str, capabilities: Any = None) -> None:
        """Set camera info after assignment."""
        self._camera_name = name

        # Update settings window with capabilities
        if self._settings_window and self._camera_id and capabilities:
            self._settings_window.update_camera_capabilities(
                self._camera_id,
                capabilities,
                hw_model=getattr(capabilities, "hw_model", None),
                backend=getattr(capabilities, "backend", None),
            )

    def set_camera_id(self, camera_id: str) -> None:
        """Set the camera ID for this view."""
        self._camera_id = camera_id

        if self._settings_window:
            self._settings_window.update_camera_defaults(camera_id)
            self._settings_window.set_active_camera(camera_id)

    def update_camera_capabilities(
        self,
        capabilities: Any,
        *,
        hw_model: Optional[str] = None,
        backend: Optional[str] = None,
    ) -> None:
        """Update camera capabilities and refresh settings options."""
        if not self._camera_id or not capabilities:
            return

        # Build resolution/FPS options from capabilities
        modes = getattr(capabilities, "modes", []) or []
        resolutions = set()
        fps_values = set()

        for mode in modes:
            w = getattr(mode, "width", None)
            h = getattr(mode, "height", None)
            fps = getattr(mode, "fps", None)
            if w and h:
                resolutions.add(f"{w}x{h}")
            if fps:
                fps_values.add(str(int(fps)))

        preview_res = sorted(resolutions, key=lambda r: -int(r.split("x")[0]))
        record_res = preview_res.copy()
        fps_list = sorted(fps_values, key=lambda f: int(f))

        self._camera_options = {
            "preview_resolutions": preview_res,
            "record_resolutions": record_res,
            "preview_fps_values": fps_list,
            "record_fps_values": fps_list,
        }

        if self._settings_window:
            self._settings_window.update_camera_options(
                self._camera_id,
                preview_resolutions=preview_res,
                record_resolutions=record_res,
                preview_fps_values=fps_list,
                record_fps_values=fps_list,
            )
            self._settings_window.update_camera_capabilities(
                self._camera_id,
                capabilities,
                hw_model=hw_model,
                backend=backend,
            )

    def set_status(self, message: str) -> None:
        """Update status message."""
        self._logger.info(message)
        if not self._has_ui or not self._status_label:
            return

        def update():
            try:
                self._status_label.config(text=message)
            except Exception:
                pass

        self._schedule_ui(update)

    def set_recording(self, is_recording: bool) -> None:
        """Update recording indicator."""
        self._is_recording = is_recording
        if not self._has_ui or not self._recording_indicator:
            return

        def update():
            try:
                color = "red" if is_recording else "gray"
                self._recording_indicator.config(fg=color)
            except Exception:
                pass

        self._schedule_ui(update)

    def push_frame(self, frame) -> None:
        """Display a preview frame."""
        if not self._has_ui or not self._canvas:
            return

        self._frame_count += 1

        def update():
            self._render_frame(frame)

        self._schedule_ui(update)

    def _render_frame(self, frame) -> None:
        """Render frame to canvas (must be called from UI thread)."""
        try:
            from PIL import Image, ImageTk
            import numpy as np

            if isinstance(frame, np.ndarray):
                # Convert BGR to RGB for PIL
                if len(frame.shape) == 3 and frame.shape[2] == 3:
                    frame = frame[:, :, ::-1]
                img = Image.fromarray(frame)
            elif isinstance(frame, bytes):
                # JPEG bytes
                import io
                img = Image.open(io.BytesIO(frame))
            else:
                img = frame

            # Get canvas size
            canvas_w = self._canvas.winfo_width()
            canvas_h = self._canvas.winfo_height()

            if canvas_w > 1 and canvas_h > 1:
                # Scale to fit canvas while maintaining aspect ratio
                img_w, img_h = img.size
                scale = min(canvas_w / img_w, canvas_h / img_h)
                new_w = int(img_w * scale)
                new_h = int(img_h * scale)
                if new_w > 0 and new_h > 0:
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # Convert to PhotoImage
            self._photo = ImageTk.PhotoImage(img)

            # Center on canvas
            x = canvas_w // 2 if canvas_w > 1 else 0
            y = canvas_h // 2 if canvas_h > 1 else 0

            self._canvas.delete("all")
            self._canvas.create_image(x, y, image=self._photo, anchor="center")

        except Exception as e:
            if self._frame_count <= 3:
                self._logger.debug("Frame render error: %s", e)

    def update_metrics(self, metrics: Dict[str, Any]) -> None:
        """Update metrics display with FPS values."""
        if not self._has_ui:
            return

        # Capture metrics: fps_capture vs target_fps
        cap_actual = metrics.get("fps_capture")
        cap_target = metrics.get("target_fps")
        cap_str = f"{_format_fps(cap_actual)} / {_format_fps(cap_target)}"
        cap_color = _fps_color(cap_actual, cap_target)

        # Record metrics: fps_encode vs target_record_fps
        rec_actual = metrics.get("fps_encode")
        rec_target = metrics.get("target_record_fps")
        rec_str = f"{_format_fps(rec_actual)} / {_format_fps(rec_target)}"
        rec_color = _fps_color(rec_actual, rec_target)

        # Display metrics: fps_preview vs target_preview_fps
        disp_actual = metrics.get("fps_preview")
        disp_target = metrics.get("target_preview_fps")
        disp_str = f"{_format_fps(disp_actual)} / {_format_fps(disp_target)}"
        disp_color = _fps_color(disp_actual, disp_target)

        def update():
            try:
                # Update values
                if "cap_tgt" in self._metrics_fields:
                    self._metrics_fields["cap_tgt"].set(cap_str)
                if "rec_tgt" in self._metrics_fields:
                    self._metrics_fields["rec_tgt"].set(rec_str)
                if "disp_tgt" in self._metrics_fields:
                    self._metrics_fields["disp_tgt"].set(disp_str)

                # Update colors
                if "cap_tgt" in self._metrics_labels and cap_color:
                    self._metrics_labels["cap_tgt"].configure(fg=cap_color)
                if "rec_tgt" in self._metrics_labels and rec_color:
                    self._metrics_labels["rec_tgt"].configure(fg=rec_color)
                if "disp_tgt" in self._metrics_labels and disp_color:
                    self._metrics_labels["disp_tgt"].configure(fg=disp_color)
            except Exception:
                pass

        self._schedule_ui(update)

    def _schedule_ui(self, func: Callable[[], None]) -> None:
        """Schedule function to run on UI thread."""
        if self._root is None:
            func()
            return

        if threading.current_thread() is self._ui_thread:
            func()
            return

        try:
            self._root.after(0, func)
        except Exception:
            pass


__all__ = ["CameraView", "DEFAULT_SETTINGS"]
