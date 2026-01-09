import asyncio
import threading
from typing import Any, Callable, Dict, Optional
import logging

from ..core.state import CameraState, CameraSettings, FRAME_RATE_OPTIONS, SAMPLE_RATE_OPTIONS
from ..core.controller import CameraController

try:
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None

logger = logging.getLogger(__name__)


def _format_fps(value: Any) -> str:
    if value is None:
        return "  --"
    try:
        return f"{float(value):5.1f}"
    except (ValueError, TypeError):
        return "  --"


def _fps_color(actual: Any, target: Any) -> Optional[str]:
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
    def __init__(self, stub_view: Any = None) -> None:
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
        self._status_var = None
        self._audio_var = None

        self._controller: Optional[CameraController] = None
        self._current_state: Optional[CameraState] = None
        self._settings_window = None
        self._frame_count = 0

    def attach(self) -> None:
        if not self._stub_view:
            return

        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:
            logger.warning("Tk unavailable: %s", exc)
            return

        stub_frame = getattr(self._stub_view, "stub_frame", None)
        if stub_frame:
            try:
                stub_frame.winfo_exists()
            except tk.TclError:
                logger.warning("View already destroyed, skipping attach")
                return

        self._tk = tk
        self._ttk = ttk
        self._ui_thread = threading.current_thread()

        def builder(parent):
            self._build_layout(parent, tk)

        self._stub_view.build_stub_content(builder)
        self._install_metrics_display(tk, ttk)
        self._install_menus()

        self._has_ui = True
        logger.info("USB Camera view attached")

    def bind_controller(self, controller: CameraController) -> None:
        self._controller = controller

    def _build_layout(self, parent, tk) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(parent, bg="black", highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_canvas_configure(self, event) -> None:
        self._canvas_width = event.width
        self._canvas_height = event.height

    def _install_metrics_display(self, tk, ttk) -> None:
        builder = getattr(self._stub_view, "build_io_stub_content", None)
        if not callable(builder):
            return

        fields = [
            ("status", "Status"),
            ("cap_tgt", "Cap In/Max"),
            ("rec_tgt", "Rec Out/Tgt"),
            ("disp_tgt", "Disp/Tgt"),
            ("audio", "Audio"),
        ]

        for key, _ in fields:
            default = "  -- /   --" if key in ("cap_tgt", "rec_tgt", "disp_tgt") else "--"
            self._metrics_fields[key] = tk.StringVar(master=self._root, value=default)

        self._status_var = self._metrics_fields.get("status")
        self._audio_var = self._metrics_fields.get("audio")

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
                    val = tk.Label(container, textvariable=self._metrics_fields[key],
                                  anchor="center", bg=bg, fg=fg2, font=("TkFixedFont", 9))
                else:
                    name = ttk.Label(container, text=label_text, anchor="center")
                    val = ttk.Label(container, textvariable=self._metrics_fields[key], anchor="center")
                name.grid(row=0, column=col, sticky="ew", padx=2)
                val.grid(row=1, column=col, sticky="ew", padx=2)
                self._metrics_labels[key] = val

        try:
            builder(_builder)
        except Exception:
            logger.debug("IO stub content build failed", exc_info=True)

    def _install_menus(self) -> None:
        view_menu = getattr(self._stub_view, "view_menu", None)
        if not view_menu:
            return

        view_menu.add_separator()
        view_menu.add_command(label="USB Camera Settings...", command=self._on_settings_click)

    def _on_settings_click(self) -> None:
        if self._settings_window:
            return

        from .widgets.settings_window import USBSettingsWindow

        state = self._current_state
        caps = state.capabilities if state else None
        settings = state.settings if state else CameraSettings()
        audio_available = state.audio_device is not None if state else False

        def on_apply(new_settings: CameraSettings):
            if self._controller:
                asyncio.create_task(self._controller.apply_settings(new_settings))

        def on_close():
            self._settings_window = None

        self._settings_window = USBSettingsWindow(
            self._root,
            capabilities=caps,
            settings=settings,
            audio_available=audio_available,
            on_apply=on_apply,
            on_close=on_close,
        )

    def render(self, state: CameraState) -> None:
        self._current_state = state

        if not self._has_ui:
            return

        if threading.current_thread() != self._ui_thread:
            if self._root:
                self._root.after(0, lambda: self.render(state))
            return

        self._update_metrics(state)
        self._update_preview(state)

    def _update_metrics(self, state: CameraState) -> None:
        status = state.phase_display
        if state.probing and state.probing_progress:
            status = state.probing_progress

        if self._status_var:
            self._status_var.set(status)

        metrics = state.metrics
        settings = state.settings

        cap_actual = metrics.capture_fps_actual
        cap_target = settings.frame_rate
        self._metrics_fields["cap_tgt"].set(f"{_format_fps(cap_actual)} / {_format_fps(cap_target)}")

        if state.recording:
            rec_actual = metrics.record_fps_actual
            self._metrics_fields["rec_tgt"].set(f"{_format_fps(rec_actual)} / {_format_fps(cap_target)}")
        else:
            self._metrics_fields["rec_tgt"].set(f"  -- / {_format_fps(cap_target)}")

        disp_actual = metrics.preview_fps_actual
        disp_target = settings.preview_fps
        self._metrics_fields["disp_tgt"].set(f"{_format_fps(disp_actual)} / {_format_fps(disp_target)}")

        if "cap_tgt" in self._metrics_labels:
            color = _fps_color(cap_actual, cap_target)
            if color:
                try:
                    self._metrics_labels["cap_tgt"].configure(fg=color)
                except Exception:
                    pass

        # Audio status
        if not state.audio_enabled:
            audio_status = "Off"
        elif state.audio_error:
            audio_status = "Error"
        elif state.audio_capturing:
            audio_status = "On"
        elif state.audio_available:
            audio_status = "Ready"
        else:
            audio_status = "N/A"

        if self._audio_var:
            self._audio_var.set(audio_status)

    def _update_preview(self, state: CameraState) -> None:
        if not state.preview_frame or not self._canvas:
            return

        self._render_preview_frame(state.preview_frame)

    def set_preview_frame(self, frame_data: bytes) -> None:
        if not self._has_ui or not self._canvas:
            return

        if threading.current_thread() != self._ui_thread:
            if self._root:
                self._root.after(0, lambda: self.set_preview_frame(frame_data))
            return

        self._render_preview_frame(frame_data)

    def _render_preview_frame(self, frame_data: bytes) -> None:
        try:
            import tkinter as tk
            self._photo = tk.PhotoImage(data=frame_data)

            if self._canvas_image_id:
                self._canvas.itemconfig(self._canvas_image_id, image=self._photo)
            else:
                cx = self._canvas_width // 2
                cy = self._canvas_height // 2
                self._canvas_image_id = self._canvas.create_image(
                    cx, cy, image=self._photo, anchor="center"
                )
            self._frame_count += 1
        except Exception as e:
            logger.warning("Preview frame error: %s", e)
