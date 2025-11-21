"""Tkinter view adapter for the Cameras runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - defensive import
    tk = None  # type: ignore
    ttk = None  # type: ignore

try:
    import cv2
except ImportError:
    cv2 = None

from PIL import Image, ImageTk

from ..hardware.media import frame_to_rgb_array
from rpi_logger.core.logging_utils import ensure_structured_logger

try:  # Pillow 10+
    DEFAULT_RESAMPLE = Image.Resampling.BILINEAR
except AttributeError:  # pragma: no cover - legacy Pillow fallback
    DEFAULT_RESAMPLE = Image.BILINEAR  # type: ignore[attr-defined]


class CameraViewAdapter:
    """Encapsulates interactions with the StubCodexView and Tk widgets."""

    PREVIEW_BACKGROUND = "#111111"

    def __init__(
        self,
        view,
        *,
        args,
        preview_size: tuple[int, int],
        task_manager,
        logger: logging.Logger,
    ) -> None:
        self.view = view
        self.args = args
        self.preview_size = preview_size
        self.task_manager = task_manager
        self.logger = ensure_structured_logger(
            logger,
            component="CameraViewAdapter",
            fallback_name=f"{__name__}.CameraViewAdapter",
        )
        self._preview_row: Optional[ttk.Frame] = None
        self._preview_uniform_group = f"camera_preview_columns_{id(self)}"
        self._preview_padx = 6
        self._preview_pady = 6
        self._current_preview_columns = 0
        self._preview_placeholder: Optional[tk.Label] = None
        self._preview_fps_var: Optional[tk.StringVar] = None
        self._preview_fraction_getter: Optional[Callable[[], Optional[float]]] = None
        self._preview_fraction_handler: Optional[Callable[[Optional[float]], Awaitable[None]]] = None
        self._last_metrics_text: Optional[str] = None
        self._frame_logged: set[int] = set()
        self._camera_toggle_vars: dict[int, tk.BooleanVar] = {}
        self._camera_toggle_labels: dict[int, str] = {}
        self._camera_toggle_handlers: dict[int, Callable[[int, bool], Awaitable[None] | None]] = {}
        self._settings_menu: Optional[tk.Menu] = None
        self._capture_controls_ready = False
        self._record_resolution_var: Optional[tk.StringVar] = None
        self._record_fps_var: Optional[tk.StringVar] = None
        self._capture_resolution_menu: Optional[tk.Menu] = None
        self._capture_rate_menu: Optional[tk.Menu] = None
        self._resolution_menu_index: Optional[int] = None
        self._rate_menu_index: Optional[int] = None
        self._io_metrics_var: Optional[tk.StringVar] = None
        self._native_stub_size = (1440, 1080)

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------
    def build_camera_grid(self, max_columns: int) -> None:
        if not self.view or tk is None:
            return

        def builder(parent: tk.Widget) -> None:
            if hasattr(parent, "configure"):
                try:
                    parent.configure(text="Camera Feeds")
                except tk.TclError:
                    pass

            if hasattr(parent, "columnconfigure"):
                parent.columnconfigure(0, weight=1)
            if hasattr(parent, "rowconfigure"):
                parent.rowconfigure(0, weight=1)

            if not isinstance(parent, tk.Frame):
                container = tk.Frame(parent, background=self.PREVIEW_BACKGROUND, bd=0, highlightthickness=0)
                container.grid(row=0, column=0, sticky="nsew")
            else:
                container = parent
            container.columnconfigure(0, weight=1)
            container.rowconfigure(0, weight=1)

            row = tk.Frame(container, background=self.PREVIEW_BACKGROUND, bd=0, highlightthickness=0)
            row.grid(row=0, column=0, sticky="nsew")

            row.rowconfigure(0, weight=1)
            self._preview_row = row
            self._show_preview_placeholder()

        self.view.build_stub_content(builder)

    def create_preview_slot(self, index: int, title: str) -> tuple[Any, Any, Any]:
        if ttk is None or self._preview_row is None:
            raise RuntimeError("Preview grid not initialized")

        self._preview_row.columnconfigure(index, weight=1)
        self._hide_preview_placeholder()

        frame = tk.Frame(
            self._preview_row,
            background="#111111",
            highlightthickness=0,
            bd=0,
        )
        frame.grid(row=0, column=index, sticky="nsew", padx=self._preview_padx, pady=self._preview_pady)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=0)
        frame.rowconfigure(1, weight=1)

        if tk is not None:
            title_label = tk.Label(
                frame,
                text=title,
                anchor="w",
                bg=self.PREVIEW_BACKGROUND,
                fg="#f5f5f5",
                font=("TkDefaultFont", 11, "bold"),
                padx=4,
            )
            title_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        canvas = tk.Canvas(
            frame,
            background="#000000",
            highlightthickness=0,
            bd=0,
        )
        canvas.grid(row=1, column=0, sticky="nsew")
        canvas.create_text(
            0,
            0,
            text="Waiting for frames…",
            fill="#cccccc",
            justify=tk.CENTER,
            anchor=tk.CENTER,
            tags="preview_text",
        )

        def _center_text(event: Any) -> None:
            canvas.coords("preview_text", event.width // 2, event.height // 2)

        canvas.bind("<Configure>", _center_text)
        canvas._preview_title = title  # type: ignore[attr-defined]

        return frame, canvas, canvas

    def _show_preview_placeholder(self) -> None:
        if tk is None or self._preview_row is None:
            return
        if self._preview_placeholder is None:
            self._preview_placeholder = tk.Label(
                self._preview_row,
                text="No camera feeds enabled.\nUse Settings ▸ Camera Feeds to show a preview.",
                bg=self.PREVIEW_BACKGROUND,
                fg="#9a9a9a",
                justify=tk.CENTER,
                anchor=tk.CENTER,
                font=("TkDefaultFont", 12),
                wraplength=420,
                padx=12,
                pady=12,
            )
        try:
            self._preview_placeholder.grid(
                row=0,
                column=0,
                sticky="nsew",
                padx=self._preview_padx,
                pady=self._preview_pady,
            )
        except tk.TclError:
            return
        self._preview_row.columnconfigure(0, weight=1)
        self._current_preview_columns = 1

    def _hide_preview_placeholder(self) -> None:
        placeholder = self._preview_placeholder
        if not placeholder:
            return
        try:
            placeholder.grid_remove()
        except tk.TclError:
            pass

    def register_camera_toggle(
        self,
        index: int,
        title: str,
        enabled: bool,
        handler: Callable[[int, bool], Awaitable[None] | None],
    ) -> None:
        if tk is None or self.view is None:
            return
        self._ensure_settings_menu()
        var = self._camera_toggle_vars.get(index)
        if var is None:
            master = self.view.root if hasattr(self.view, "root") else None
            var = tk.BooleanVar(master=master, value=enabled)
            self._camera_toggle_vars[index] = var
        else:
            try:
                var.set(enabled)
            except tk.TclError:
                pass
        self._camera_toggle_labels[index] = title
        self._camera_toggle_handlers[index] = handler
        self._rebuild_settings_menu()

    def update_camera_toggle_state(self, index: int, enabled: bool) -> None:
        var = self._camera_toggle_vars.get(index)
        if not var:
            return
        try:
            var.set(enabled)
        except tk.TclError:
            pass

    def bind_preview_resize(self, frame: Any, callback: Callable[[int, int], None]) -> None:
        if tk is None:
            return

        def _on_configure(event: Any) -> None:
            try:
                width = max(int(event.width), 1)
                height = max(int(event.height), 1)
            except Exception:
                return
            callback(width, height)

        try:
            frame.bind("<Configure>", _on_configure)
        except Exception:  # pragma: no cover - defensive
            pass

    def prime_preview_dimensions(self, frame: Any, callback: Callable[[int, int], None]) -> None:
        def _capture() -> None:
            try:
                width = max(frame.winfo_width(), 1)
                height = max(frame.winfo_height(), 1)
            except Exception:
                return
            callback(width, height)

        try:
            frame.after(0, _capture)
        except Exception:  # pragma: no cover - defensive
            pass

    # ------------------------------------------------------------------
    # Preview FPS menu wiring
    # ------------------------------------------------------------------
    def install_preview_fps_menu(
        self,
        getter: Callable[[], Optional[float]],
        handler: Callable[[Optional[float]], Awaitable[None]],
    ) -> None:
        self._preview_fraction_getter = getter
        self._preview_fraction_handler = handler

        if not self.view or tk is None:
            return
        self._ensure_settings_menu()
        self._ensure_preview_fps_var()
        self._rebuild_settings_menu()

    def refresh_preview_fps_ui(self) -> None:
        if not self._preview_fps_var or not self._preview_fraction_getter:
            return
        key = self._preview_fraction_key_for_value(self._preview_fraction_getter())
        try:
            self._preview_fps_var.set(key)
        except Exception:  # pragma: no cover - defensive
            pass

    def _ensure_preview_fps_var(self) -> tk.StringVar:
        if self._preview_fps_var is not None:
            return self._preview_fps_var
        master = self.view.root if self.view else None
        current = self._preview_fraction_key_for_value(self._preview_fraction_getter()) if self._preview_fraction_getter else "full"
        self._preview_fps_var = tk.StringVar(master=master, value=current)
        return self._preview_fps_var

    def _ensure_settings_menu(self) -> Optional[tk.Menu]:
        if tk is None or not self.view:
            return None
        if self._menu_exists(self._settings_menu):
            return self._settings_menu

        menu: Optional[tk.Menu] = None
        add_menu = getattr(self.view, "add_menu", None)
        if callable(add_menu):
            menu = add_menu("Settings")

        if menu is None:
            menubar = getattr(self.view, "menubar", None)
            if menubar is None:
                return None
            menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label="Settings", menu=menu)

        self._settings_menu = menu
        return menu

    def _menu_exists(self, menu: Optional[tk.Menu]) -> bool:
        if menu is None:
            return False
        try:
            return bool(menu.winfo_exists())
        except Exception:
            return False

    def _rebuild_settings_menu(self) -> None:
        if tk is None:
            return
        settings_menu = self._ensure_settings_menu()
        if settings_menu is None:
            return
        try:
            settings_menu.delete(0, "end")
        except tk.TclError:
            pass

        self._resolution_menu_index = None
        self._rate_menu_index = None
        has_entries = False

        if self._preview_fraction_getter and self._preview_fraction_handler:
            var = self._ensure_preview_fps_var()
            settings_menu.add_command(label="Preview Refresh Rate", state=tk.DISABLED)
            for key, label, fraction in self._preview_fraction_options():
                settings_menu.add_radiobutton(
                    label=label,
                    value=key,
                    variable=var,
                    command=lambda value=fraction: self._handle_preview_fraction_selection(value),
                )
            has_entries = True

        if self._camera_toggle_vars:
            if has_entries:
                settings_menu.add_separator()
            settings_menu.add_command(label="Camera Feeds", state=tk.DISABLED)
            for camera_index in sorted(self._camera_toggle_vars):
                var = self._camera_toggle_vars[camera_index]
                label = self._camera_toggle_labels.get(camera_index, f"Camera {camera_index + 1}")
                settings_menu.add_checkbutton(
                    label=label,
                    variable=var,
                    command=lambda idx=camera_index: self._handle_camera_toggle(idx),
                )
            has_entries = True

        capture_sections = [
            ("Resolution", self._capture_resolution_menu, "resolution"),
            ("Frame Rate", self._capture_rate_menu, "rate"),
        ]
        if any(menu is not None for _, menu, _ in capture_sections):
            if has_entries:
                settings_menu.add_separator()
            for label, submenu, token in capture_sections:
                if submenu is None:
                    continue
                settings_menu.add_cascade(label=label, menu=submenu)
                try:
                    index = settings_menu.index("end")
                except tk.TclError:
                    index = None
                if token == "resolution":
                    self._resolution_menu_index = index
                elif token == "rate":
                    self._rate_menu_index = index

    def _preview_fraction_options(self) -> list[tuple[str, str, float]]:
        return [
            ("full", "Full (100%)", 1.0),
            ("half", "Half (50%)", 0.5),
            ("third", "One Third (33%)", 1 / 3),
            ("quarter", "Quarter (25%)", 0.25),
        ]

    def _preview_fraction_key_for_value(self, fraction: Optional[float]) -> str:
        if fraction is None or fraction <= 0:
            return "full"
        for key, _label, value in self._preview_fraction_options():
            if abs(value - fraction) < 1e-3:
                return key
        return "full"

    def _handle_preview_fraction_selection(self, fraction_value: Optional[float]) -> None:
        if not self._preview_fraction_handler:
            return
        if self.task_manager:
            self.task_manager.create(
                self._preview_fraction_handler(fraction_value),
                name="PreviewFractionUpdate",
            )
        else:
            asyncio.create_task(self._preview_fraction_handler(fraction_value))

    # ------------------------------------------------------------------
    # Record toggle & capture menu
    # ------------------------------------------------------------------
    def configure_capture_menu(self) -> None:
        if not self.view or tk is None:
            return
        if self._capture_controls_ready and self._menu_exists(self._settings_menu):
            return

        settings_menu = self._ensure_settings_menu()
        if settings_menu is None:
            return

        master = self.view.root if hasattr(self.view, "root") else None

        resolution_menu = tk.Menu(settings_menu, tearoff=0)
        self._record_resolution_var = tk.StringVar(master=master, value=self._initial_record_resolution_key())
        for key, label, _size in self._record_resolution_choices():
            resolution_menu.add_radiobutton(
                label=label,
                value=key,
                variable=self._record_resolution_var,
                command=lambda option=key: self._on_record_resolution(option),
            )
        self._capture_resolution_menu = resolution_menu

        rate_menu = tk.Menu(settings_menu, tearoff=0)
        self._record_fps_var = tk.StringVar(master=master, value=self._initial_record_fps_key())
        for key, label, _fps in self._record_fps_choices():
            rate_menu.add_radiobutton(
                label=label,
                value=key,
                variable=self._record_fps_var,
                command=lambda option=key: self._on_record_fps(option),
            )
        self._capture_rate_menu = rate_menu

        self._capture_controls_ready = True
        self._rebuild_settings_menu()
        self.set_capture_controls_enabled(True)

    def sync_record_toggle(self, enabled: bool, *, capture_disabled: bool) -> None:
        if tk is None:
            return
        self.set_capture_controls_enabled(not capture_disabled)

    def set_capture_controls_enabled(self, enabled: bool) -> None:
        if tk is None or not self._menu_exists(self._settings_menu):
            return
        state = tk.NORMAL if enabled else tk.DISABLED
        settings_menu = self._settings_menu
        if settings_menu is None:
            return
        for index in (self._resolution_menu_index, self._rate_menu_index):
            if index is None:
                continue
            try:
                settings_menu.entryconfig(index, state=state)
            except Exception:  # pragma: no cover - defensive
                continue

    def _on_record_resolution(self, key: str) -> None:
        value = self._record_resolution_value(key)
        if value == "native":
            self._dispatch_record_settings({"size": "native"})
        elif value:
            self._dispatch_record_settings({"size": value})

    def _on_record_fps(self, key: str) -> None:
        fps_value = self._record_fps_value(key)
        self._dispatch_record_settings({"fps": fps_value})

    def _record_resolution_choices(self) -> list[tuple[str, str, Optional[tuple[int, int]]]]:
        return [
            ("native", "Native (1440 × 1080)", None),
            ("1280x960", "1280 × 960", (1280, 960)),
            ("960x720", "960 × 720", (960, 720)),
            ("720x540", "720 × 540", (720, 540)),
            ("640x480", "640 × 480", (640, 480)),
            ("480x360", "480 × 360", (480, 360)),
            ("320x240", "320 × 240", (320, 240)),
            ("160x120", "160 × 120", (160, 120)),
        ]

    def _record_fps_choices(self) -> list[tuple[str, str, Optional[float]]]:
        return [
            ("unlimited", "Unlimited", None),
            ("60fps", "60 fps", 60.0),
            ("30fps", "30 fps", 30.0),
            ("15fps", "15 fps", 15.0),
            ("5fps", "5 fps", 5.0),
        ]

    def _initial_record_resolution_key(self) -> str:
        width = getattr(self.args, "save_width", None)
        height = getattr(self.args, "save_height", None)
        key = self._match_resolution_key(width, height, self._record_resolution_choices())
        return key or "native"

    def _initial_record_fps_key(self) -> str:
        fps = getattr(self.args, "save_fps", None)
        try:
            fps_value = float(fps) if fps is not None else None
        except (TypeError, ValueError):
            fps_value = None
        if fps_value and fps_value > 0:
            key = self._match_fps_key(fps_value, self._record_fps_choices())
            if key:
                return key
        return "unlimited"

    def _match_resolution_key(
        self,
        width: Optional[int],
        height: Optional[int],
        choices: list[tuple[str, str, Optional[tuple[int, int]]]],
    ) -> Optional[str]:
        if width is None or height is None:
            return None
        try:
            width = int(width)
            height = int(height)
        except (TypeError, ValueError):
            return None
        for key, _label, size in choices:
            if size and size[0] == width and size[1] == height:
                return key
            if size is None and width == self._native_stub_size[0] and height == self._native_stub_size[1]:
                return key
        return None

    def _match_fps_key(
        self,
        fps: float,
        choices: list[tuple[str, str, Optional[float]]],
    ) -> Optional[str]:
        for key, _label, value in choices:
            if value is None:
                continue
            if abs(value - fps) < 0.1:
                return key
        return None

    def _record_resolution_value(self, key: str) -> Optional[tuple[int, int]] | str | None:
        for option, _label, size in self._record_resolution_choices():
            if option == key:
                if size is None:
                    return "native"
                return size
        return None

    def _record_fps_value(self, key: str) -> float:
        for option, _label, value in self._record_fps_choices():
            if option == key:
                return 0.0 if value in (None, 0) else float(value)
        return 0.0

    def _dispatch_record_settings(self, settings: dict[str, Any]) -> None:
        if not self.view:
            return
        action_callback = getattr(self.view, "action_callback", None)
        if not action_callback:
            return
        try:
            result = action_callback("update_record_settings", **settings)
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.error("Record settings dispatch failed: %s", exc)
            return
        if asyncio.iscoroutine(result):
            if self.task_manager:
                try:
                    self.task_manager.create(result, name="UpdateRecordSettings")
                except RuntimeError:
                    asyncio.create_task(result)
            else:
                asyncio.create_task(result)

    # ------------------------------------------------------------------
    # IO metrics display
    # ------------------------------------------------------------------
    def install_io_metrics_panel(self) -> None:
        if not self.view or tk is None or ttk is None:
            return
        builder = getattr(self.view, "build_io_stub_content", None)
        if not callable(builder):
            return
        set_title = getattr(self.view, "set_io_stub_title", None)
        if callable(set_title):
            set_title("Pipeline Metrics")

        master = self.view.root if hasattr(self.view, "root") else None

        def _builder(parent) -> None:
            parent.columnconfigure(0, weight=1)
            var = tk.StringVar(master=master, value=self._default_metrics_text())
            label = ttk.Label(parent, textvariable=var, anchor="w", font=("TkDefaultFont", 10))
            label.grid(row=0, column=0, sticky="ew")
            self._io_metrics_var = var

        builder(_builder)
        self._last_metrics_text = None

    def _default_metrics_text(self) -> str:
        return "Capture FPS: -- | Process FPS: -- | View FPS: -- | Save FPS: --"

    def update_pipeline_metrics(
        self,
        *,
        capture_fps: float,
        process_fps: float,
        preview_fps: float,
        storage_fps: float,
    ) -> None:
        if tk is None or self._io_metrics_var is None:
            return
        root = getattr(self.view, "root", None) if self.view else None
        if root is None:
            return

        text = self._format_pipeline_metrics(
            capture_fps=capture_fps,
            process_fps=process_fps,
            preview_fps=preview_fps,
            storage_fps=storage_fps,
        )

        if text == self._last_metrics_text:
            return
        self._last_metrics_text = text

        def _update() -> None:
            try:
                self._io_metrics_var.set(text)
            except tk.TclError:  # pragma: no cover - defensive
                pass

        try:
            root.after(0, _update)
        except Exception:  # pragma: no cover - defensive
            pass

    def show_camera_placeholder(self, slot, message: str) -> None:
        if tk is None:
            return
        widget = getattr(slot, "label", None)
        if widget is None:
            return

        def _update() -> None:
            if not widget.winfo_exists():
                return
            width = widget.winfo_width() or self.preview_size[0]
            height = widget.winfo_height() or self.preview_size[1]
            widget.delete("preview_image")
            widget.delete("preview_text")
            widget.create_text(
                width // 2,
                height // 2,
                text=message,
                fill="#cccccc",
                justify=tk.CENTER,
                anchor=tk.CENTER,
                tags="preview_text",
            )

        try:
            widget.after(0, _update)
        except Exception:
            pass

    def show_camera_hidden(self, slot) -> None:
        title = getattr(slot, "title", "Camera")
        self.show_camera_placeholder(slot, f"{title} disabled (Settings ▸ Camera Feeds)")

    def show_camera_waiting(self, slot) -> None:
        title = getattr(slot, "title", "")
        message = f"Waiting for {title or 'camera'}…"
        self.show_camera_placeholder(slot, message)

    def refresh_preview_layout(self, slots: list[Any]) -> None:
        if tk is None or self._preview_row is None:
            return

        total_columns = max(self._current_preview_columns, len(slots), 1)
        for col in range(total_columns):
            self._preview_row.columnconfigure(col, weight=0, uniform=None)

        active_slots: list[Any] = []
        for slot in slots:
            if not getattr(slot, "preview_enabled", True):
                continue
            frame = getattr(slot, "frame", None)
            if frame is None:
                continue
            try:
                if not frame.winfo_exists():
                    continue
            except tk.TclError:
                continue
            active_slots.append(slot)

        if not active_slots:
            for slot in slots:
                frame = getattr(slot, "frame", None)
                if frame is not None:
                    try:
                        frame.grid_remove()
                    except tk.TclError:
                        pass
            self._show_preview_placeholder()
            self._current_preview_columns = 0
            return

        self._hide_preview_placeholder()
        uniform_value = self._preview_uniform_group if len(active_slots) > 1 else None
        active_slot_ids = {id(slot) for slot in active_slots}
        active_col = 0

        for slot in active_slots:
            frame = getattr(slot, "frame", None)
            if frame is None:
                continue
            try:
                frame.grid(
                    row=0,
                    column=active_col,
                    sticky="nsew",
                    padx=self._preview_padx,
                    pady=self._preview_pady,
                )
            except tk.TclError:
                active_col += 1
                continue
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=0)
            frame.rowconfigure(1, weight=1)
            self._preview_row.columnconfigure(active_col, weight=1, uniform=uniform_value)
            active_col += 1

        for slot in slots:
            if id(slot) in active_slot_ids:
                continue
            frame = getattr(slot, "frame", None)
            if frame is not None:
                try:
                    frame.grid_remove()
                except tk.TclError:
                    pass

        self._current_preview_columns = active_col

    def _format_pipeline_metrics(
        self,
        *,
        capture_fps: float,
        process_fps: float,
        preview_fps: float,
        storage_fps: float,
    ) -> str:
        def _fmt(value: float) -> str:
            return f"{value:.1f}" if value > 0 else "--"

        return (
            f"Capture FPS: {_fmt(capture_fps)}"
            f" | Process FPS: {_fmt(process_fps)}"
            f" | View FPS: {_fmt(preview_fps)}"
            f" | Save FPS: {_fmt(storage_fps)}"
        )

    # ------------------------------------------------------------------
    # Preview rendering
    # ------------------------------------------------------------------
    def view_is_resizing(self) -> bool:
        view = self.view
        if view and hasattr(view, "is_resizing"):
            try:
                return bool(view.is_resizing())
            except Exception:  # pragma: no cover - defensive
                return False
        return False

    async def display_frame(self, slot, frame: Any, pixel_format: str) -> bool:
        if self.view_is_resizing():
            return False
        if not getattr(slot, "preview_enabled", True):
            return False

        stream_size = getattr(slot, "preview_stream_size", None) or getattr(slot, "main_size", None)
        target_size = getattr(slot, "size", self.preview_size) or self.preview_size
        if target_size[0] <= 0 or target_size[1] <= 0:
            target_size = self.preview_size
        native_size = getattr(slot, "preview_stream_size", None)

        image, source_size, resized = await asyncio.to_thread(
            self._prepare_preview_image,
            frame,
            pixel_format,
            stream_size,
            target_size,
            native_size,
        )

        self._log_preview_scaling(slot.index, source_size, target_size, resized)

        master = self.view.root if self.view else None
        photo = ImageTk.PhotoImage(image, master=master)
        widget = getattr(slot, "label", None)
        if widget is None:
            return False

        def _update() -> None:
            if not widget.winfo_exists():
                return
            if isinstance(widget, tk.Canvas):
                width = widget.winfo_width() or target_size[0]
                height = widget.winfo_height() or target_size[1]
                widget.delete("preview_image")
                widget.delete("preview_text")
                widget.create_image(
                    width // 2,
                    height // 2,
                    image=photo,
                    anchor=tk.CENTER,
                    tags="preview_image",
                )
                widget.image = photo  # type: ignore[attr-defined]
            else:
                widget.configure(image=photo, text="")
                widget.image = photo  # type: ignore[attr-defined]

        try:
            widget.after(0, _update)
            return True
        except Exception:  # pragma: no cover - defensive
            return False

    def _prepare_preview_image(
        self,
        frame: Any,
        pixel_format: str,
        stream_size: Optional[tuple[int, int]],
        target_size: tuple[int, int],
        native_size: Optional[tuple[int, int]],
    ) -> tuple[Image.Image, tuple[int, int], bool]:
        # Optimization: Resize using OpenCV on the RGB array before Pillow conversion
        # This avoids the expensive PIL resize operation.
        rgb_array = None
        if cv2 is not None:
             rgb_array = frame_to_rgb_array(frame, pixel_format, size_hint=stream_size)

        if rgb_array is not None:
            source_h, source_w = rgb_array.shape[:2]
            source_size = (source_w, source_h)
            
            # Handle cropping (e.g. if stream is padded)
            if native_size and (source_w > native_size[0] or source_h > native_size[1]):
                crop_w = min(native_size[0], source_w)
                crop_h = min(native_size[1], source_h)
                rgb_array = rgb_array[:crop_h, :crop_w]
                source_size = (crop_w, crop_h)

            resized = False
            if source_size != target_size:
                # cv2.resize expects (width, height)
                rgb_array = cv2.resize(rgb_array, target_size, interpolation=cv2.INTER_LINEAR)
                resized = True
            
            return Image.fromarray(rgb_array, mode="RGB"), source_size, resized

        # Fallback to original Pillow path
        from ..hardware.media import frame_to_image as convert_frame_to_image
        image = convert_frame_to_image(frame, pixel_format, size_hint=stream_size)
        source_size = image.size

        if native_size and (image.width > native_size[0] or image.height > native_size[1]):
            crop_width = min(native_size[0], image.width)
            crop_height = min(native_size[1], image.height)
            image = image.crop((0, 0, crop_width, crop_height))

        resized = False
        if image.size != target_size:
            image = image.resize(target_size, DEFAULT_RESAMPLE)
            resized = True

        return image, source_size, resized

    def _log_preview_scaling(
        self,
        index: int,
        source_size: tuple[int, int],
        target_size: tuple[int, int],
        resized: bool,
    ) -> None:
        if index in self._frame_logged:
            return
        if resized:
            self.logger.info(
                "Camera %s frame size %s differs from preview slot %s; resizing",
                index,
                source_size,
                target_size,
            )
        else:
            self.logger.info(
                "Camera %s frame size %s matches preview slot",
                index,
                source_size,
            )
        self._frame_logged.add(index)

    def _handle_camera_toggle(self, index: int) -> None:
        handler = self._camera_toggle_handlers.get(index)
        var = self._camera_toggle_vars.get(index)
        if handler is None or var is None:
            return
        enabled = bool(var.get())
        result = handler(index, enabled)
        if asyncio.iscoroutine(result):
            try:
                if self.task_manager:
                    self.task_manager.create(result, name=f"CameraToggle{index}")
                else:
                    asyncio.create_task(result)
            except RuntimeError as exc:
                # Window can emit toggles during shutdown; ignore instead of crashing.
                self.logger.debug("Ignoring toggle while shutting down: %s", exc)


__all__ = ["CameraViewAdapter"]
