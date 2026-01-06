"""Single-camera view: preview canvas, metrics, and settings."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.base.camera_validator import CapabilityValidator
from rpi_logger.modules.Cameras.app.widgets.camera_settings_window import CameraSettingsWindow, DEFAULT_SETTINGS

try:
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME, Colors = False, None


def _format_fps(v: Any) -> str:
    try:
        return f"{float(v):5.1f}" if v is not None else "  --"
    except (ValueError, TypeError):
        return "  --"


def _fps_color(actual: Any, target: Any) -> Optional[str]:
    if not HAS_THEME or Colors is None:
        return None
    try:
        if actual is not None and target is not None and float(target) > 0:
            pct = (float(actual) / float(target)) * 100
            return Colors.SUCCESS if pct >= 95 else (Colors.WARNING if pct >= 80 else Colors.ERROR)
    except (ValueError, TypeError):
        pass
    return Colors.FG_PRIMARY


class CameraView:
    """Single-camera view: preview, metrics, settings."""

    def __init__(self, stub_view: Any = None, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._stub_view, self._root = stub_view, getattr(stub_view, "root", None)
        self._ui_thread = threading.current_thread()
        self._canvas = self._photo = self._canvas_image_id = None
        self._canvas_width = self._canvas_height = 0
        self._has_ui = False
        self._metrics_fields: Dict[str, Any] = {}
        self._metrics_labels: Dict[str, Any] = {}
        self._settings_window: Optional[CameraSettingsWindow] = None
        self._settings_toggle_var = self._settings_menu = None
        self._config_handler: Optional[Callable[[str, Dict[str, str]], None]] = None
        self._control_change_handler: Optional[Callable[[str, str, Any], None]] = None
        self._reprobe_handler: Optional[Callable[[str], None]] = None
        self._camera_id: Optional[str] = None
        self._camera_name: Optional[str] = None
        self._frame_count = 0
        self._camera_settings: Dict[str, str] = dict(DEFAULT_SETTINGS)
        self._camera_options: Dict[str, List[str]] = {}

    def attach(self) -> None:
        if not self._stub_view:
            return
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception:
            return
        self._ui_thread = threading.current_thread()
        self._stub_view.build_stub_content(lambda p: self._build_layout(p, tk))
        self._install_metrics_display(tk, ttk)
        self._install_settings_window(tk)
        self._install_settings_menu(tk)
        self._has_ui = True

    def bind_handlers(self, *, apply_config=None, control_change=None, reprobe=None) -> None:
        self._config_handler, self._control_change_handler, self._reprobe_handler = apply_config, control_change, reprobe

    def _build_layout(self, parent, tk) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        container = tk.Frame(parent, bg=Colors.BG_FRAME if HAS_THEME and Colors else "black")
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self._canvas = tk.Canvas(container, bg="black", highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<Configure>", self._on_canvas_configure)


    def _install_metrics_display(self, tk, ttk) -> None:
        builder = getattr(self._stub_view, "build_io_stub_content", None)
        if not callable(builder):
            self._logger.warning("build_io_stub_content not available - no metrics display")
            return
        fields = [("cap_tgt", "Cap In/Tgt"), ("rec_tgt", "Rec Out/Tgt"), ("disp_tgt", "Disp/Tgt")]
        for key, _ in fields:
            self._metrics_fields[key] = tk.StringVar(master=self._root, value="  -- /   --")
        def _builder(frame):
            bg = Colors.BG_FRAME if HAS_THEME and Colors else None
            container = tk.Frame(frame, bg=bg) if HAS_THEME else ttk.Frame(frame)
            container.grid(row=0, column=0, sticky="ew")
            for idx in range(len(fields)):
                container.columnconfigure(idx, weight=1, uniform="iofields")
            for col, (key, label_text) in enumerate(fields):
                if HAS_THEME and Colors:
                    name = tk.Label(container, text=label_text, anchor="center", bg=bg, fg=Colors.FG_SECONDARY)
                    val = tk.Label(container, textvariable=self._metrics_fields[key], anchor="center", bg=bg, fg=Colors.FG_PRIMARY, font=("TkFixedFont", 9))
                else:
                    name, val = ttk.Label(container, text=label_text, anchor="center"), ttk.Label(container, textvariable=self._metrics_fields[key], anchor="center")
                name.grid(row=0, column=col, sticky="ew", padx=2)
                val.grid(row=1, column=col, sticky="ew", padx=2)
                self._metrics_labels[key] = val
        try:
            builder(_builder)
            self._logger.debug("Metrics display installed: %d fields", len(self._metrics_fields))
        except Exception:
            self._logger.debug("IO stub content build failed", exc_info=True)

    def _install_settings_window(self, tk) -> None:
        if self._settings_toggle_var is None:
            self._settings_toggle_var = tk.BooleanVar(master=self._root, value=False)
        if self._settings_window is None:
            self._settings_window = CameraSettingsWindow(self._root, logger=self._logger, on_apply_resolution=self._on_apply_config, on_control_change=self._on_control_change, on_reprobe=self._on_reprobe)
            self._settings_window.bind_toggle_var(self._settings_toggle_var)

    def _install_settings_menu(self, tk) -> None:
        if self._settings_menu:
            return
        if (fm := getattr(self._stub_view, "file_menu", None)) and self._settings_toggle_var:
            fm.add_separator()
            fm.add_checkbutton(label="Camera Settings", variable=self._settings_toggle_var, command=self._toggle_settings_window)
        if (vm := getattr(self._stub_view, "view_menu", None)):
            self._settings_menu = vm
            vm.add_command(label="Reprobe Camera", command=lambda: self._on_reprobe(self._camera_id))
        for fn in ["finalize_view_menu", "finalize_file_menu"]:
            if callable(f := getattr(self._stub_view, fn, None)):
                f()

    def _toggle_settings_window(self) -> None:
        if not self._settings_window or not self._settings_toggle_var:
            return
        if self._settings_toggle_var.get():
            if self._camera_id:
                self._settings_window.set_camera_settings(self._camera_id, self._camera_settings)
                self._settings_window.set_active_camera(self._camera_id)
            self._settings_window.show()
        else:
            self._settings_window.hide()

    def _on_canvas_configure(self, event) -> None:
        self._canvas_width, self._canvas_height = event.width, event.height
        self._canvas_image_id = None

    def get_canvas_size(self) -> tuple:
        return (self._canvas_width, self._canvas_height) if self._canvas_width > 1 and self._canvas_height > 1 else (640, 480)

    def _on_apply_config(self, camera_id: str, settings: Dict[str, str]) -> None:
        if not camera_id:
            return
        self._camera_settings.update(settings)
        if self._config_handler:
            try:
                self._config_handler(camera_id, settings)
            except Exception:
                pass

    def _on_control_change(self, camera_id: str, control_name: str, value: Any) -> None:
        if self._control_change_handler:
            try:
                self._control_change_handler(camera_id, control_name, value)
            except Exception:
                pass

    def _on_reprobe(self, camera_id: Optional[str] = None) -> None:
        if (target := camera_id or self._camera_id) and self._reprobe_handler:
            try:
                self._reprobe_handler(target)
            except Exception:
                pass

    def set_camera_info(self, name: str, capabilities: Any = None) -> None:
        self._camera_name = name
        if self._settings_window and self._camera_id and capabilities:
            self._settings_window.update_camera_capabilities(self._camera_id, capabilities, hw_model=getattr(capabilities, "hw_model", None), backend=getattr(capabilities, "backend", None))

    def set_camera_id(self, camera_id: str) -> None:
        self._camera_id = camera_id
        if self._settings_window:
            self._settings_window.update_camera_defaults(camera_id)
            self._settings_window.set_active_camera(camera_id)

    def set_has_audio_sibling(self, has_audio: bool) -> None:
        """Set whether this camera has a built-in microphone.

        This controls visibility of the audio recording checkbox in settings.
        """
        if self._settings_window and self._camera_id:
            self._settings_window.set_camera_has_audio_sibling(self._camera_id, has_audio)

    def update_camera_capabilities(
        self,
        capabilities: Any,
        *,
        hw_model: Optional[str] = None,
        backend: Optional[str] = None,
        sensor_info: Optional[Dict[str, Any]] = None,
        display_name: Optional[str] = None,
    ) -> None:
        """Update camera capabilities and refresh settings options.

        Uses CapabilityValidator to ensure UI only shows valid options.
        """
        if not self._camera_id or not capabilities:
            return

        # Create validator to extract valid options from capabilities
        validator = CapabilityValidator(capabilities)

        # Get resolution and FPS options from validator
        preview_res = validator.available_resolutions()
        record_res = preview_res.copy()
        fps_list = validator.all_fps_values()

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
            self._logger.debug("update_metrics called but no UI")
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
