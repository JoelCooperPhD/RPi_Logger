"""CSI2 Camera view with preview and metrics.

Stateless UI driven by Store subscriptions, attaches to stub (codex) view.
Controls via CLI args (--camera-index, --record) and View menu (Settings).
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Awaitable, Dict, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger

try:
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None

_module_dir = Path(__file__).resolve().parent.parent
if str(_module_dir) not in sys.path:
    sys.path.insert(0, str(_module_dir))

from core import (
    AppState, CameraStatus, RecordingStatus,
    Action, ApplySettings, CameraSettings,
)


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


class CSI2CameraView:
    """Stateless view driven by Store state, attaches to stub (codex) view."""

    def __init__(self, stub_view: Any = None, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
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

        self._dispatch: Optional[Callable[[Action], Awaitable[None]]] = None
        self._current_state: Optional[AppState] = None
        self._settings_window = None
        self._frame_count = 0

    def attach(self) -> None:
        if not self._stub_view:
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
        self._logger.info("CSI2 Camera view attached")

    def bind_dispatch(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        self._dispatch = dispatch

    def _build_layout(self, parent, tk) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(parent, bg="black", highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<Configure>", self._on_canvas_configure)

    def _install_metrics_display(self, tk, ttk) -> None:
        builder = getattr(self._stub_view, "build_io_stub_content", None)
        if not callable(builder):
            return

        fields = [
            ("cap_tgt", "Cap In/Max"),
            ("rec_tgt", "Rec Out/Tgt"),
            ("disp_tgt", "Disp/Tgt"),
        ]

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
            self._logger.debug("IO stub content build failed", exc_info=True)

    def _install_menus(self) -> None:
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
        self._canvas_width = event.width
        self._canvas_height = event.height
        self._canvas_image_id = None

    def get_canvas_size(self) -> tuple:
        if self._canvas_width > 1 and self._canvas_height > 1:
            return (self._canvas_width, self._canvas_height)
        return (640, 480)

    def _on_settings_click(self) -> None:
        if self._settings_window is not None:
            try:
                self._settings_window.lift()
                return
            except Exception:
                self._settings_window = None

        if self._root is None:
            return

        from ui.widgets.settings_window import SettingsWindow

        current_settings = CameraSettings()
        capabilities = None
        if self._current_state:
            current_settings = self._current_state.settings
            capabilities = self._current_state.capabilities

        def on_apply(new_settings: CameraSettings) -> None:
            self._settings_window = None
            if self._dispatch:
                asyncio.create_task(self._dispatch(ApplySettings(new_settings)))

        self._settings_window = SettingsWindow(
            self._root,
            current_settings=current_settings,
            capabilities=capabilities,
            on_apply=on_apply,
        )

    def render(self, state: AppState) -> None:
        if not self._has_ui:
            return

        self._current_state = state

        def update():
            self._render_state(state)

        self._schedule_ui(update)

    def _render_state(self, state: AppState) -> None:
        metrics = state.metrics
        settings = state.settings

        cap_actual = metrics.capture_fps_actual
        cap_target = settings.capture_fps
        self._metrics_fields["cap_tgt"].set(f"{_format_fps(cap_actual)} /   MAX")

        if state.recording_status == RecordingStatus.RECORDING:
            rec_actual = metrics.capture_fps_actual
            rec_target = settings.record_fps
            self._metrics_fields["rec_tgt"].set(f"{_format_fps(rec_actual)} / {_format_fps(rec_target)}")
        else:
            self._metrics_fields["rec_tgt"].set("  -- /   --")

        disp_actual = metrics.capture_fps_actual
        disp_target = settings.preview_fps
        if disp_actual and cap_target:
            disp_actual = disp_actual * (settings.preview_fps / cap_target) if cap_target > 0 else 0
        self._metrics_fields["disp_tgt"].set(f"{_format_fps(disp_actual)} / {_format_fps(disp_target)}")

        if "cap_tgt" in self._metrics_labels:
            color = _fps_color(cap_actual, cap_target)
            if color:
                try:
                    self._metrics_labels["cap_tgt"].configure(fg=color)
                except Exception:
                    pass

    def push_frame(self, ppm_data: Optional[bytes]) -> None:
        if not self._has_ui or not self._canvas:
            return

        self._frame_count += 1

        def update():
            self._render_frame(ppm_data)

        self._schedule_ui(update)

    def _render_frame(self, ppm_data: Optional[bytes]) -> None:
        try:
            if ppm_data is None:
                return

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

        except Exception as e:
            if self._frame_count <= 3:
                self._logger.debug("Frame render error: %s", e)

    def _schedule_ui(self, func: Callable[[], None]) -> None:
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


__all__ = ["CSI2CameraView"]
