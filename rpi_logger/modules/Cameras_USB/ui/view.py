"""USB Camera view with preview and metrics.

Stateless UI driven by state callbacks, attaches to stub (codex) view.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional

from ..core import CameraState, Phase, RecordingPhase

logger = logging.getLogger(__name__)

try:
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None


def _format_fps(value: Any) -> str:
    """Format FPS value for display."""
    if value is None:
        return "  --"
    try:
        return f"{float(value):5.1f}"
    except (ValueError, TypeError):
        return "  --"


def _fps_color(actual: Any, target: Any) -> Optional[str]:
    """Get color based on FPS performance."""
    if not HAS_THEME or Colors is None:
        return None
    try:
        if actual is not None and target is not None and float(target) > 0:
            pct = (float(actual) / float(target)) * 100
            if pct >= 95:
                return Colors.SUCCESS
            elif pct >= 80:
                return Colors.WARNING
            else:
                return Colors.ERROR
    except (ValueError, TypeError):
        pass
    return Colors.FG_PRIMARY


class USBCameraView:
    """Stateless view driven by state callbacks, attaches to stub (codex) view."""

    def __init__(self, stub_view: Any = None, *, logger_instance=None) -> None:
        """Initialize view.

        Args:
            stub_view: The stub (codex) view from ctx.view
            logger_instance: Optional logger
        """
        self._logger = logger_instance or logger
        self._stub_view = stub_view
        self._root = getattr(stub_view, "root", None)
        self._ui_thread = threading.current_thread()

        self._canvas = None
        self._photo = None
        self._canvas_image_id = None
        self._canvas_width = 0
        self._canvas_height = 0
        self._has_ui = False

        self._metrics_fields: Dict[str, Any] = {}
        self._metrics_labels: Dict[str, Any] = {}
        self._tk = None

        self._current_state: Optional[CameraState] = None
        self._settings_window = None
        self._settings_callback: Optional[Callable] = None
        self._frame_count = 0

    def set_settings_callback(self, callback: Callable) -> None:
        """Set callback for settings changes.

        Args:
            callback: Function that accepts a Settings object
        """
        self._settings_callback = callback

    def attach(self) -> None:
        """Attach to the stub (codex) view."""
        if not self._stub_view:
            self._logger.info("No stub view available (headless mode)")
            return

        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:
            self._logger.warning("Tk unavailable: %s", exc)
            return

        self._tk = tk
        self._ui_thread = threading.current_thread()

        def builder(parent):
            self._build_layout(parent, tk)

        self._stub_view.build_stub_content(builder)
        self._install_metrics_display(tk, ttk)
        self._install_menus()

        self._has_ui = True
        self._logger.info("USB Camera view attached")

    def _build_layout(self, parent, tk) -> None:
        """Build the main preview canvas layout."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(parent, bg="black", highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<Configure>", self._on_canvas_configure)

    def _install_metrics_display(self, tk, ttk) -> None:
        """Install metrics display in the IO panel."""
        builder = getattr(self._stub_view, "build_io_stub_content", None)
        if not callable(builder):
            return

        fields = [
            ("hw_fps", "Hardware"),
            ("rec_fps", "Record"),
            ("disp_fps", "Preview"),
            ("audio", "Audio"),
            ("status", "Status"),
        ]

        for key, _ in fields:
            if key == "status":
                initial = "Ready"
            elif key == "audio":
                initial = "--"
            else:
                initial = "  -- /   --"
            self._metrics_fields[key] = tk.StringVar(master=self._root, value=initial)

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
                    name = tk.Label(container, text=label_text, anchor="center", bg=bg, fg=fg1)
                    val = tk.Label(
                        container,
                        textvariable=self._metrics_fields[key],
                        anchor="center",
                        bg=bg,
                        fg=fg2,
                        font=("TkFixedFont", 9),
                    )
                else:
                    name = ttk.Label(container, text=label_text, anchor="center")
                    val = ttk.Label(container, textvariable=self._metrics_fields[key], anchor="center")
                name.grid(row=0, column=col, sticky="ew", padx=2)
                val.grid(row=1, column=col, sticky="ew", padx=2)
                self._metrics_labels[key] = val

        try:
            builder(_builder)
        except Exception:
            self._logger.debug("IO stub content build failed", exc_info=True)

    def _install_menus(self) -> None:
        """Install menu items."""
        view_menu = getattr(self._stub_view, "view_menu", None)
        if view_menu is not None:
            view_menu.add_command(label="Camera Settings...", command=self._on_settings_click)

        finalize_view = getattr(self._stub_view, "finalize_view_menu", None)
        if callable(finalize_view):
            finalize_view()

        finalize_file = getattr(self._stub_view, "finalize_file_menu", None)
        if callable(finalize_file):
            finalize_file()

    def _on_canvas_configure(self, event) -> None:
        """Handle canvas resize."""
        self._canvas_width = event.width
        self._canvas_height = event.height
        self._canvas_image_id = None

    def _on_settings_click(self) -> None:
        """Handle settings menu click."""
        if self._settings_window is not None:
            try:
                self._settings_window.lift()
                return
            except Exception:
                self._settings_window = None

        if self._root is None or self._current_state is None:
            return

        self._show_settings_dialog()

    def _show_settings_dialog(self) -> None:
        """Show the settings dialog window."""
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception:
            return

        settings = self._current_state.settings

        # Create toplevel window
        win = tk.Toplevel(self._root)
        win.title("USB Camera Settings")
        win.transient(self._root)
        win.resizable(False, False)

        self._settings_window = win

        def on_close():
            self._settings_window = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

        # Main frame with padding
        main = ttk.Frame(win, padding=15)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)

        # Consistent dropdown width for alignment
        COMBO_WIDTH = 18

        # Helper to create a settings row with right-aligned dropdown
        def add_setting_row(row_num, label_text, var, values):
            """Add a row with label on left and dropdown on right."""
            ttk.Label(main, text=label_text).grid(
                row=row_num, column=0, sticky="w", pady=6, padx=(0, 20)
            )
            combo = ttk.Combobox(
                main, textvariable=var, values=values,
                width=COMBO_WIDTH, state="readonly"
            )
            combo.grid(row=row_num, column=1, sticky="e", pady=6)
            return combo

        def add_section_header(row_num, text):
            """Add a section header with separator."""
            ttk.Label(main, text=text, font=("TkDefaultFont", 9, "bold")).grid(
                row=row_num, column=0, columnspan=2, sticky="w", pady=(12, 4)
            )

        row = 0

        # --- VIDEO ---
        add_section_header(row, "Video")
        row += 1

        # Resolution
        res_str = f"{settings.resolution[0]}x{settings.resolution[1]}"
        res_var = tk.StringVar(value=res_str)
        res_values = ["320x240", "640x480", "800x600", "1280x720", "1920x1080"]
        if res_str not in res_values:
            res_values.insert(0, res_str)
        add_setting_row(row, "Resolution", res_var, res_values)
        row += 1

        # Frame rate
        fps_var = tk.StringVar(value=str(settings.frame_rate))
        add_setting_row(row, "Frame Rate", fps_var,
                        ["10", "15", "24", "30", "60"])
        row += 1

        # --- PREVIEW ---
        add_section_header(row, "Preview")
        row += 1

        # Preview scale - human readable values
        scale_display_map = {
            0.125: "12.5% (tiny)",
            0.25: "25% (small)",
            0.5: "50% (medium)",
            1.0: "100% (full size)",
        }
        scale_values = list(scale_display_map.values())
        current_scale_display = scale_display_map.get(
            settings.preview_scale, f"{int(settings.preview_scale * 100)}%"
        )
        scale_var = tk.StringVar(value=current_scale_display)
        add_setting_row(row, "Preview Size", scale_var, scale_values)
        row += 1

        # Preview divisor - human readable values
        div_display_map = {
            1: "Every frame (smoothest)",
            2: "Every 2nd frame",
            4: "Every 4th frame",
            8: "Every 8th frame (fastest)",
        }
        div_values = list(div_display_map.values())
        current_div_display = div_display_map.get(
            settings.preview_divisor, f"Every {settings.preview_divisor} frames"
        )
        div_var = tk.StringVar(value=current_div_display)
        add_setting_row(row, "Preview Update Rate", div_var, div_values)
        row += 1

        # --- AUDIO ---
        add_section_header(row, "Audio")
        row += 1

        # Audio enabled checkbox
        audio_var = tk.BooleanVar(value=settings.audio_enabled)
        audio_check = ttk.Checkbutton(
            main, text="Enable audio recording", variable=audio_var
        )
        audio_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=6)
        row += 1

        # Sample rate
        rate_var = tk.StringVar(value=str(settings.sample_rate))
        add_setting_row(row, "Sample Rate", rate_var,
                        ["44100", "48000", "96000"])
        row += 1

        # Info text
        ttk.Separator(main, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(15, 10)
        )
        row += 1

        info_text = "Changes take effect on next stream start."
        ttk.Label(main, text=info_text, foreground="gray").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        row += 1

        # Button frame - right-aligned
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=row, column=0, columnspan=2, sticky="e")

        # Reverse lookup maps for parsing display values back to settings values
        scale_reverse_map = {v: k for k, v in scale_display_map.items()}
        div_reverse_map = {v: k for k, v in div_display_map.items()}

        def on_apply():
            try:
                from ..core import Settings

                # Parse resolution
                res_parts = res_var.get().split("x")
                if len(res_parts) == 2:
                    resolution = (int(res_parts[0]), int(res_parts[1]))
                else:
                    resolution = settings.resolution

                # Parse preview scale from display string
                scale_display = scale_var.get()
                preview_scale = scale_reverse_map.get(scale_display, settings.preview_scale)

                # Parse preview divisor from display string
                div_display = div_var.get()
                preview_divisor = div_reverse_map.get(div_display, settings.preview_divisor)

                new_settings = Settings(
                    resolution=resolution,
                    frame_rate=int(fps_var.get()),
                    preview_divisor=preview_divisor,
                    preview_scale=preview_scale,
                    audio_enabled=audio_var.get(),
                    audio_device_index=settings.audio_device_index,
                    sample_rate=int(rate_var.get()),
                    audio_channels=settings.audio_channels,
                )
                if self._settings_callback:
                    self._settings_callback(new_settings)
                self._logger.info(
                    "Settings updated: res=%dx%d, fps=%d, scale=%.2f, audio=%s",
                    resolution[0], resolution[1],
                    new_settings.frame_rate, new_settings.preview_scale,
                    new_settings.audio_enabled
                )
            except Exception as e:
                self._logger.error("Failed to apply settings: %s", e)

        def on_ok():
            on_apply()
            on_close()

        ttk.Button(btn_frame, text="Cancel", command=on_close, width=8).pack(
            side="left", padx=(0, 5)
        )
        ttk.Button(btn_frame, text="Apply", command=on_apply, width=8).pack(
            side="left", padx=(0, 5)
        )
        ttk.Button(btn_frame, text="OK", command=on_ok, width=8).pack(side="left")

        # Center the window
        win.update_idletasks()
        x = self._root.winfo_x() + (self._root.winfo_width() - win.winfo_width()) // 2
        y = self._root.winfo_y() + (self._root.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")

    def render(self, state: CameraState) -> None:
        """Render state changes to the UI.

        Args:
            state: Current camera state
        """
        if not self._has_ui:
            return

        self._current_state = state

        def update():
            self._render_state(state)

        self._schedule_ui(update)

    def _render_state(self, state: CameraState) -> None:
        """Render state to metrics display."""
        metrics = state.metrics
        settings = state.settings

        # Hardware FPS
        hw_fps = metrics.hardware_fps
        target = settings.frame_rate
        self._metrics_fields["hw_fps"].set(f"{_format_fps(hw_fps)} fps")

        # Record FPS
        if state.recording_phase == RecordingPhase.RECORDING:
            rec_fps = metrics.record_fps
            self._metrics_fields["rec_fps"].set(f"{_format_fps(rec_fps)} / {_format_fps(target)}")
        else:
            self._metrics_fields["rec_fps"].set(f"  -- / {_format_fps(target)}")

        # Preview FPS
        disp_fps = metrics.preview_fps
        preview_target = target / settings.preview_divisor
        self._metrics_fields["disp_fps"].set(f"{_format_fps(disp_fps)} / {_format_fps(preview_target)}")

        # Audio status with color coding
        if "audio" in self._metrics_fields:
            if not state.has_audio:
                # No microphone detected for this camera
                audio_text = "No Mic"
                audio_color = Colors.FG_SECONDARY if HAS_THEME and Colors else None
            elif not settings.audio_enabled:
                # Mic available but disabled by user
                audio_text = "Disabled"
                audio_color = Colors.FG_SECONDARY if HAS_THEME and Colors else None
            elif state.recording_phase == RecordingPhase.RECORDING:
                # Actively recording audio
                chunks = metrics.audio_chunks
                audio_text = f"Rec ({chunks})"
                audio_color = "#2ecc71"  # green
            else:
                # Mic ready, waiting to record
                audio_text = "Ready"
                audio_color = "#3498db"  # blue

            self._metrics_fields["audio"].set(audio_text)
            if "audio" in self._metrics_labels and audio_color:
                try:
                    self._metrics_labels["audio"].configure(fg=audio_color)
                except Exception:
                    pass

        # Color coding for hardware FPS
        if "hw_fps" in self._metrics_labels:
            color = _fps_color(hw_fps, target)
            if color:
                try:
                    self._metrics_labels["hw_fps"].configure(fg=color)
                except Exception:
                    pass

        # Camera status with color coding
        if "status" in self._metrics_fields:
            phase = state.phase
            if phase == Phase.IDLE:
                status_text = "Ready"
                status_color = Colors.FG_SECONDARY if HAS_THEME and Colors else None
            elif phase == Phase.STARTING:
                status_text = "Connecting..."
                status_color = "#f39c12"  # orange
            elif phase == Phase.STREAMING:
                status_text = "Streaming"
                status_color = "#2ecc71"  # green
            elif phase == Phase.ERROR:
                status_text = "Error"
                status_color = "#e74c3c"  # red
            else:
                status_text = str(phase.name)
                status_color = None

            self._metrics_fields["status"].set(status_text)
            if "status" in self._metrics_labels and status_color:
                try:
                    self._metrics_labels["status"].configure(fg=status_color)
                except Exception:
                    pass

    def push_frame(self, ppm_data: Optional[bytes]) -> None:
        """Push a preview frame to the canvas.

        Args:
            ppm_data: PPM format image data
        """
        if not self._has_ui or not self._canvas:
            if self._frame_count == 0:
                self._logger.warning("push_frame: no UI (has_ui=%s, canvas=%s)",
                                     self._has_ui, self._canvas is not None)
            return

        self._frame_count += 1

        if self._frame_count <= 3:
            self._logger.info("push_frame: frame %d, data_len=%d",
                              self._frame_count, len(ppm_data) if ppm_data else 0)

        def update():
            self._render_frame(ppm_data)

        self._schedule_ui(update)

    def _render_frame(self, ppm_data: Optional[bytes]) -> None:
        """Render a frame to the canvas."""
        try:
            if ppm_data is None:
                return

            if self._frame_count <= 3:
                self._logger.info("_render_frame: creating PhotoImage, canvas=%dx%d",
                                  self._canvas_width, self._canvas_height)

            self._photo = self._tk.PhotoImage(data=ppm_data)

            x = self._canvas_width // 2 if self._canvas_width > 1 else 0
            y = self._canvas_height // 2 if self._canvas_height > 1 else 0

            if self._canvas_image_id is not None:
                self._canvas.itemconfig(self._canvas_image_id, image=self._photo)
                self._canvas.coords(self._canvas_image_id, x, y)
            else:
                self._canvas_image_id = self._canvas.create_image(
                    x, y, image=self._photo, anchor="center"
                )
                if self._frame_count <= 3:
                    self._logger.info("_render_frame: created image at (%d, %d)", x, y)

        except Exception as e:
            # Always log render errors - they indicate a real problem
            self._logger.error("Frame render error: %s", e, exc_info=True)

    def _schedule_ui(self, func: Callable[[], None]) -> None:
        """Schedule a function to run on the UI thread."""
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


__all__ = ["USBCameraView"]
