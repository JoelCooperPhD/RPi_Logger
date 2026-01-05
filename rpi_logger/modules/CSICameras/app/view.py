"""Single-camera view for CSICameras module.

Each CSICameras instance displays exactly one camera. This view provides
the preview canvas, status display, metrics, and settings configuration.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.CSICameras.app.widgets.camera_settings_window import (
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


class CSICameraView:
    """Single-camera view with preview canvas, status, metrics, and settings."""

    def __init__(self, stub_view: Any = None, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._stub_view = stub_view
        self._root = getattr(stub_view, "root", None)
        self._ui_thread = threading.current_thread()

        # UI elements
        self._canvas = None
        self._photo = None
        self._canvas_image_id = None  # Reusable canvas image item
        self._canvas_width = 0
        self._canvas_height = 0
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
        self._frame_count: int = 0
        self._camera_settings: Dict[str, str] = dict(DEFAULT_SETTINGS)
        self._camera_options: Dict[str, List[str]] = {}

    def attach(self) -> None:
        """Mount the camera view inside the stub view frame."""
        if not self._stub_view:
            self._logger.info("CSI Camera view running headless (no stub view)")
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
        self._logger.info("CSI Camera view attached")

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

        container = tk.Frame(parent, bg=bg_color)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        # Canvas for video preview
        self._canvas = tk.Canvas(container, bg="black", highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<Configure>", self._on_canvas_configure)


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
        """Add camera items to File and View menus."""
        if self._settings_menu:
            return

        # Add Camera Settings to File menu
        file_menu = getattr(self._stub_view, "file_menu", None)
        if file_menu is not None and self._settings_toggle_var is not None:
            file_menu.add_separator()
            file_menu.add_checkbutton(
                label="Camera Settings",
                variable=self._settings_toggle_var,
                command=self._toggle_settings_window,
            )

        # Get the View menu from the stub view
        view_menu = getattr(self._stub_view, "view_menu", None)
        if view_menu is not None:
            self._settings_menu = view_menu
            # Reprobe camera command
            view_menu.add_command(
                label="Reprobe Camera",
                command=lambda: self._on_reprobe(self._camera_id),
            )

        # Finalize View menu (adds Capture Stats, Logger)
        finalize_view = getattr(self._stub_view, "finalize_view_menu", None)
        if callable(finalize_view):
            finalize_view()

        # Finalize File menu (adds Quit)
        finalize_file = getattr(self._stub_view, "finalize_file_menu", None)
        if callable(finalize_file):
            finalize_file()

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

    def _on_canvas_configure(self, event) -> None:
        """Handle canvas resize events."""
        self._canvas_width = event.width
        self._canvas_height = event.height
        # Reset canvas image to force reposition on next frame
        self._canvas_image_id = None

    def get_canvas_size(self) -> tuple:
        """Return current canvas dimensions for preview scaling."""
        if self._canvas_width > 1 and self._canvas_height > 1:
            return (self._canvas_width, self._canvas_height)
        # Fallback to default preview size
        return (640, 480)

    def _on_apply_config(self, camera_id: str, settings: Dict[str, str]) -> None:
        """Handle config apply from settings window."""
        self._logger.debug("_on_apply_config called: camera_id=%s, settings=%s", camera_id, settings)
        if not camera_id:
            return

        self._camera_settings.update(settings)

        if self._config_handler:
            self._logger.debug("Calling config handler")
            try:
                self._config_handler(camera_id, settings)
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
            return

        if self._reprobe_handler:
            try:
                self._reprobe_handler(target)
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
        sensor_info: Optional[Dict[str, Any]] = None,
        display_name: Optional[str] = None,
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
                sensor_info=sensor_info,
                display_name=display_name,
            )


    def push_frame(self, ppm_data: Optional[bytes]) -> None:
        """Display a preview frame (PPM bytes, pre-scaled in capture task)."""
        if not self._has_ui or not self._canvas:
            return

        self._frame_count += 1

        def update():
            self._render_frame(ppm_data)

        self._schedule_ui(update)

    def _render_frame(self, ppm_data: Optional[bytes]) -> None:
        """Render PPM bytes to canvas (must be called from UI thread).

        The image is pre-scaled and serialized as PPM by the capture task.
        Only fast PPM decoding happens on the Tk thread.
        """
        try:
            import tkinter as tk

            if ppm_data is None:
                return

            # Fast PhotoImage from PPM bytes (no PIL on Tk thread)
            self._photo = tk.PhotoImage(data=ppm_data)

            # Center position
            x = self._canvas_width // 2 if self._canvas_width > 1 else 0
            y = self._canvas_height // 2 if self._canvas_height > 1 else 0

            # Reuse existing canvas image item or create new one
            if self._canvas_image_id is not None:
                # Update existing image in place (much faster than delete/create)
                self._canvas.itemconfig(self._canvas_image_id, image=self._photo)
                self._canvas.coords(self._canvas_image_id, x, y)
            else:
                # First frame or after canvas resize - create new item
                self._canvas_image_id = self._canvas.create_image(
                    x, y, image=self._photo, anchor="center"
                )

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


__all__ = ["CSICameraView", "DEFAULT_SETTINGS"]
