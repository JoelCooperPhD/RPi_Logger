"""View component responsible for the interactive placeholder window."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from async_tkinter_loop import async_handler

try:
    import tkinter as tk  # type: ignore
    from tkinter import ttk, scrolledtext  # type: ignore
except Exception as exc:  # pragma: no cover - defensive import
    tk = None  # type: ignore
    ttk = None  # type: ignore
    scrolledtext = None  # type: ignore
    TK_IMPORT_ERROR = exc
else:
    TK_IMPORT_ERROR = None

from .model import StubCodexModel
from .constants import PLACEHOLDER_GEOMETRY

_BASE_LOGGER = logging.getLogger(__name__)

class StubCodexView:
    """Tkinter view that mirrors model state and forwards user intent."""

    def __init__(
        self,
        args,
        model: StubCodexModel,
        action_callback: Optional[Callable[..., Awaitable[None]]] = None,
        *,
        display_name: str,
        enable_camera_controls: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        start = time.perf_counter()

        self.args = args
        self.model = model
        self.action_callback = action_callback
        self.display_name = display_name
        self.enable_camera_controls = enable_camera_controls
        self.logger = logger or _BASE_LOGGER
        self._close_requested = False
        self._window_duration_ms: float = 0.0
        self._loop_running = False
        self._log_handler: Optional[logging.Handler] = None
        self._last_geometry: Optional[str] = None
        self._geometry_save_handle: Optional[asyncio.Handle] = None
        self._geometry_save_delay = 0.25
        self.io_view_frame: Optional[ttk.LabelFrame] = None
        self.io_view_visible_var: Optional[tk.BooleanVar] = None
        self.io_metrics_var: Optional[tk.StringVar] = None
        self.io_metrics_label: Optional[ttk.Label] = None
        self.stub_frame: Optional[ttk.LabelFrame] = None
        self.native_size = (1440, 1080)
        self._resize_active = False
        self._resize_reset_handle: Optional[str] = None
        self._resize_idle_delay = 0.15
        self._logged_first_configure = False

        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - defensive
            self._event_loop = None

        if tk is None or ttk is None or scrolledtext is None:
            raise RuntimeError(f"tkinter unavailable: {TK_IMPORT_ERROR}")

        self.root = tk.Tk()
        self.root.title(self.display_name)
        self.root.report_callback_exception = self._log_tk_exception  # type: ignore[attr-defined]

        geometry = getattr(args, "window_geometry", None) or PLACEHOLDER_GEOMETRY
        if isinstance(geometry, str):
            self.root.geometry(geometry)
        else:
            self.root.geometry(PLACEHOLDER_GEOMETRY)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.model.subscribe(self._on_model_change)

        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass

        self._last_geometry = self._current_geometry_string()
        self.root.bind("<Configure>", self._on_configure)

        elapsed = (time.perf_counter() - start) * 1000.0
        self.logger.info("StubCodexView initialized in %.2f ms", elapsed)

    # ------------------------------------------------------------------
    # UI construction

    def _build_ui(self) -> None:
        assert tk is not None and ttk is not None and scrolledtext is not None

        self.io_view_visible_var = tk.BooleanVar(value=True)
        self.log_visible_var = tk.BooleanVar(value=True)

        self.record_enabled_var: Optional[tk.BooleanVar] = None
        self.record_resolution_var: Optional[tk.StringVar] = None
        self.record_fps_var: Optional[tk.StringVar] = None
        self.record_format_var: Optional[tk.StringVar] = None
        self.record_quality_var: Optional[tk.StringVar] = None

        if self.enable_camera_controls:
            self.record_enabled_var = tk.BooleanVar(value=bool(getattr(self.args, "save_images", False)))
            self.record_resolution_var = tk.StringVar(value=self._initial_record_resolution_key())
            self.record_fps_var = tk.StringVar(value=self._initial_record_fps_key())
            initial_format = str(getattr(self.args, "save_format", "jpeg")).lower()
            if initial_format == "jpg":
                initial_format = "jpeg"
            self.record_format_var = tk.StringVar(value=initial_format)
            self.record_quality_var = tk.StringVar(value=self._initial_record_quality_key())

        self.capture_menu: Optional[tk.Menu] = None
        self.capture_resolution_menu: Optional[tk.Menu] = None
        self.capture_rate_menu: Optional[tk.Menu] = None
        self.capture_format_menu: Optional[tk.Menu] = None
        self.capture_quality_menu: Optional[tk.Menu] = None
        self.capture_resolution_index: Optional[int] = None
        self.capture_rate_index: Optional[int] = None
        self.capture_format_index: Optional[int] = None
        self.capture_quality_index: Optional[int] = None

        self.menubar: Optional[tk.Menu] = None
        self._create_menu_bar()

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.root, padding="12")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=0)
        main_frame.rowconfigure(2, weight=0)

        self.stub_frame = ttk.LabelFrame(main_frame, text="Stub", padding="10")
        self.stub_frame.grid(row=0, column=0, sticky="nsew")
        self.logger.info("Stub frame added to main layout")

        self.io_view_frame = ttk.LabelFrame(main_frame, text="IO Stub", padding="8")
        self.io_view_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.io_view_frame.columnconfigure(0, weight=1)
        self.io_view_frame.rowconfigure(0, weight=1)

        self.io_metrics_var = tk.StringVar(value=self._default_io_metrics_text())
        self.io_metrics_label = ttk.Label(
            self.io_view_frame,
            textvariable=self.io_metrics_var,
            anchor="w",
            font=("TkDefaultFont", 10),
        )
        self.io_metrics_label.grid(row=0, column=0, sticky="w")

        self.log_frame = ttk.LabelFrame(main_frame, text="Logger", padding="8")
        self.log_frame.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            self.log_frame,
            height=2,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#f5f5f5",
            fg="#333333",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        self._toggle_io_view()
        self._toggle_log_visibility()

    # ------------------------------------------------------------------
    # Stub content integration

    def build_stub_content(self, builder: Callable[[tk.Widget], None]) -> None:
        """Replace the stub frame contents using the provided builder."""

        if self.stub_frame is None:
            return

        for child in list(self.stub_frame.winfo_children()):
            child.destroy()

        builder(self.stub_frame)

        try:
            self.stub_frame.update_idletasks()
        except tk.TclError:
            pass

    def _create_menu_bar(self) -> None:
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        self.menubar = menubar

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Log File", command=self._open_log_file)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_quit_clicked)

        if self.enable_camera_controls:
            self._create_camera_menus(menubar)

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_checkbutton(
            label="Show IO Stub",
            variable=self.io_view_visible_var,
            command=self._toggle_io_view,
        )
        view_menu.add_checkbutton(
            label="Show Logger",
            variable=self.log_visible_var,
            command=self._toggle_log_visibility,
        )

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Quick Start Guide", command=self._show_help)

    def add_menu(self, label: str, *, tearoff: int = 0) -> Optional[tk.Menu]:
        if self.menubar is None:
            return None
        menu = tk.Menu(self.menubar, tearoff=tearoff)
        self.menubar.add_cascade(label=label, menu=menu)
        return menu

    def _create_camera_menus(self, menubar: tk.Menu) -> None:
        if not self.enable_camera_controls:
            return

        if (
            self.record_enabled_var is None
            or self.record_resolution_var is None
            or self.record_fps_var is None
            or self.record_format_var is None
            or self.record_quality_var is None
        ):
            self.logger.warning("Camera controls requested but not initialized; skipping menu setup")
            return

        capture_menu = tk.Menu(menubar, tearoff=0)
        self.capture_menu = capture_menu
        menubar.add_cascade(label="Settings", menu=capture_menu)
        capture_menu.add_checkbutton(
            label="Enable Frame Capture",
            variable=self.record_enabled_var,
            command=self._on_record_toggle,
        )

        self.capture_resolution_menu = tk.Menu(capture_menu, tearoff=0)
        capture_menu.add_cascade(label="Resolution", menu=self.capture_resolution_menu)
        self.capture_resolution_index = capture_menu.index("end")
        for key, label, size in self._record_resolution_choices():
            self.capture_resolution_menu.add_radiobutton(
                label=label,
                value=key,
                variable=self.record_resolution_var,
                command=lambda opt=key: self._on_record_resolution(opt),
            )

        self.capture_rate_menu = tk.Menu(capture_menu, tearoff=0)
        capture_menu.add_cascade(label="Frame Rate", menu=self.capture_rate_menu)
        self.capture_rate_index = capture_menu.index("end")
        for key, label, fps in self._record_fps_choices():
            self.capture_rate_menu.add_radiobutton(
                label=label,
                value=key,
                variable=self.record_fps_var,
                command=lambda opt=key: self._on_record_fps(opt),
            )

        self.capture_format_menu = tk.Menu(capture_menu, tearoff=0)
        capture_menu.add_cascade(label="Format", menu=self.capture_format_menu)
        self.capture_format_index = capture_menu.index("end")
        for key, label in self._record_format_choices():
            self.capture_format_menu.add_radiobutton(
                label=label,
                value=key,
                variable=self.record_format_var,
                command=lambda opt=key: self._on_record_format(opt),
            )

        self.capture_quality_menu = tk.Menu(capture_menu, tearoff=0)
        capture_menu.add_cascade(label="Quality", menu=self.capture_quality_menu)
        self.capture_quality_index = capture_menu.index("end")
        for key, label, quality in self._record_quality_choices():
            self.capture_quality_menu.add_radiobutton(
                label=label,
                value=key,
                variable=self.record_quality_var,
                command=lambda opt=key: self._on_record_quality(opt),
            )

        self._update_capture_menu_state()

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

    def _record_format_choices(self) -> list[tuple[str, str]]:
        return [
            ("jpeg", "JPEG"),
            ("png", "PNG"),
            ("webp", "WebP"),
        ]

    def _record_quality_choices(self) -> list[tuple[str, str, int]]:
        return [
            ("q95", "High (95)", 95),
            ("q85", "Balanced (85)", 85),
            ("q70", "Economy (70)", 70),
        ]

    def _initial_record_resolution_key(self) -> str:
        width = getattr(self.args, "save_width", None)
        height = getattr(self.args, "save_height", None)
        key = self._match_resolution_key(width, height, self._record_resolution_choices())
        return key or "native"

    def _initial_record_fps_key(self) -> str:
        fps = getattr(self.args, "save_fps", None)
        if fps and float(fps) > 0:
            key = self._match_fps_key(float(fps), self._record_fps_choices())
            if key:
                return key
        return "unlimited"

    def _initial_record_quality_key(self) -> str:
        quality = getattr(self.args, "save_quality", 90)
        if quality is None:
            return "q85"
        try:
            quality = int(quality)
        except (TypeError, ValueError):
            quality = 90
        for key, _label, value in self._record_quality_choices():
            if value == quality:
                return key
        return "q85"

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
        native_width, native_height = self.native_size
        for key, _label, size in choices:
            if size and size[0] == width and size[1] == height:
                return key
            if size is None and width == native_width and height == native_height:
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

    def _update_capture_menu_state(self) -> None:
        if (
            not self.enable_camera_controls
            or self.capture_menu is None
            or self.record_enabled_var is None
        ):
            return
        state = tk.NORMAL if self.record_enabled_var.get() else tk.DISABLED
        for index in (
            getattr(self, "capture_resolution_index", None),
            getattr(self, "capture_rate_index", None),
            getattr(self, "capture_format_index", None),
            getattr(self, "capture_quality_index", None),
        ):
            if index is not None:
                self.capture_menu.entryconfig(index, state=state)

    def _record_resolution_value(self, key: str) -> Optional[tuple[int, int]] | str:
        for option, _label, size in self._record_resolution_choices():
            if option == key:
                if size is None:
                    return "native" if option == "native" else self.native_size
                return size
        return "native"

    def _record_fps_value(self, key: str) -> float:
        for option, _label, fps in self._record_fps_choices():
            if option == key:
                return 0.0 if fps in (None, 0) else float(fps)
        return 0.0

    def _record_quality_value(self, key: str) -> Optional[int]:
        for option, _label, quality in self._record_quality_choices():
            if option == key:
                return quality
        return None

    def _on_record_toggle(self) -> None:
        if not self.enable_camera_controls or self.record_enabled_var is None:
            return
        enabled = self.record_enabled_var.get()
        payload: dict[str, Any] = {"enabled": enabled}
        directory = getattr(self.args, "save_dir", None)
        if enabled and directory:
            payload["directory"] = str(directory)
        self._dispatch_record_settings(payload)
        self._update_capture_menu_state()

    def _on_record_resolution(self, key: str) -> None:
        if not self.enable_camera_controls:
            return
        value = self._record_resolution_value(key)
        if value == "native":
            self._dispatch_record_settings({"size": "native"})
        else:
            self._dispatch_record_settings({"size": value})

    def _on_record_fps(self, key: str) -> None:
        if not self.enable_camera_controls:
            return
        fps = self._record_fps_value(key)
        self._dispatch_record_settings({"fps": fps})

    def _on_record_format(self, key: str) -> None:
        if not self.enable_camera_controls:
            return
        self._dispatch_record_settings({"format": key})

    def _on_record_quality(self, key: str) -> None:
        if not self.enable_camera_controls:
            return
        quality = self._record_quality_value(key)
        if quality is not None:
            self._dispatch_record_settings({"quality": quality})

    @async_handler
    async def _dispatch_record_settings(self, settings: dict[str, Any]) -> None:
        if self.action_callback:
            await self.action_callback("update_record_settings", **settings)

    # ------------------------------------------------------------------
    # IO view helpers

    def _default_io_metrics_text(self) -> str:
        return "Capture FPS: -- | Process FPS: -- | View FPS: -- | Save FPS: --"

    def _toggle_io_view(self) -> None:
        if not self.io_view_frame or not self.io_view_visible_var:
            return
        if self.io_view_visible_var.get():
            self.io_view_frame.grid()
        else:
            self.io_view_frame.grid_remove()

    def show_io_stub(self) -> None:
        if not self.io_view_frame or not self.io_view_visible_var:
            return
        self.io_view_visible_var.set(True)
        self.io_view_frame.grid()

    def hide_io_stub(self) -> None:
        if not self.io_view_frame or not self.io_view_visible_var:
            return
        self.io_view_visible_var.set(False)
        self.io_view_frame.grid_remove()

    def _log_tk_exception(self, exc_type, exc_value, exc_tb) -> None:
        self.logger.error(
            "Tkinter callback failed: %s",
            exc_value,
            exc_info=(exc_type, exc_value, exc_tb),
        )

    # ------------------------------------------------------------------
    # Logging integration

    def attach_logging_handler(self) -> None:
        if self._log_handler is not None or self.log_text is None:
            return

        class TextHandler(logging.Handler):
            def __init__(self, widget):
                super().__init__()
                self.widget = widget
                self.setFormatter(
                    logging.Formatter(
                        '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
                        datefmt='%H:%M:%S',
                    )
                )

            def emit(self, record):
                message = self.format(record) + '\n'
                try:
                    self.widget.after(0, self._append, message)
                except (tk.TclError, RuntimeError):
                    return

            def _append(self, message: str) -> None:
                try:
                    self.widget.config(state=tk.NORMAL)
                    self.widget.insert(tk.END, message)
                    self.widget.see(tk.END)
                    lines = int(float(self.widget.index('end-1c')))
                    if lines > 500:
                        self.widget.delete('1.0', f'{lines-500}.0')
                    self.widget.config(state=tk.DISABLED)
                except (tk.TclError, RuntimeError):
                    return

        handler = TextHandler(self.log_text)
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)
        self._log_handler = handler

    def _detach_logging_handler(self) -> None:
        if self._log_handler is None:
            return
        try:
            logging.getLogger().removeHandler(self._log_handler)
        finally:
            self._log_handler = None

    # ------------------------------------------------------------------
    # Menu actions

    def _toggle_log_visibility(self) -> None:
        if not self.log_frame or not self.log_visible_var:
            return
        if self.log_visible_var.get():
            self.log_frame.grid()
        else:
            self.log_frame.grid_remove()

    def show_logger(self) -> None:
        if not self.log_frame or not self.log_visible_var:
            return
        self.log_visible_var.set(True)
        self.log_frame.grid()

    def hide_logger(self) -> None:
        if not self.log_frame or not self.log_visible_var:
            return
        self.log_visible_var.set(False)
        self.log_frame.grid_remove()

    def _open_log_file(self) -> None:
        log_file = self._resolve_log_file()
        if log_file is None:
            self.logger.warning("Log file path unavailable yet")
            return
        if not log_file.exists():
            self.logger.warning("Log file does not exist: %s", log_file)
            return

        try:
            if sys.platform.startswith('linux'):
                subprocess.Popen(['xdg-open', str(log_file)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(log_file)])
            elif sys.platform == 'win32':
                subprocess.Popen(['notepad.exe', str(log_file)])
            else:
                self.logger.warning("Unsupported platform for opening files: %s", sys.platform)
        except Exception as exc:
            self.logger.error("Failed to open log file: %s", exc)

    def _show_help(self) -> None:
        try:
            from logger_core.ui.help_dialogs import QuickStartDialog
            QuickStartDialog(self.root)
        except Exception as exc:
            self.logger.error("Failed to open help dialog: %s", exc)

    def _resolve_log_file(self) -> Optional[Path]:
        if getattr(self.model, 'log_file', None):
            return Path(self.model.log_file)
        if getattr(self.args, 'log_file', None):
            return Path(self.args.log_file)
        return None

    # ------------------------------------------------------------------
    # Quit handling

    @async_handler
    async def _on_quit_clicked(self) -> None:
        if self.action_callback:
            await self.action_callback("quit")
        self._on_close()

    def _on_close(self) -> None:
        if self._close_requested:
            return
        self._close_requested = True
        self._cancel_geometry_save_handle(flush=True)
        if self.action_callback:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.action_callback("quit"))
            except RuntimeError:
                pass
        self.root.quit()

    # ------------------------------------------------------------------
    # Model observation

    def _on_model_change(self, prop: str, value) -> None:
        self.logger.debug("Model change: %s -> %s", prop, value)

    # ------------------------------------------------------------------
    # Lifecycle

    async def run(self) -> float:
        self.logger.info("StubCodexView run loop starting")
        if self._event_loop is None:
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._event_loop = None
        if self._loop_running:
            return 0.0
        self._loop_running = True
        open_time = time.perf_counter()
        try:
            while not self._close_requested:
                try:
                    self.root.update()
                except tk.TclError as exc:
                    self.logger.error("Tk root.update() raised: %s", exc, exc_info=exc)
                    break
                await asyncio.sleep(0.01)
        finally:
            self._window_duration_ms = max(0.0, (time.perf_counter() - open_time) * 1000.0)
            self._loop_running = False
            self.logger.info("StubCodexView run loop finished (%.2f ms)", self._window_duration_ms)
        return self._window_duration_ms

    def get_geometry(self) -> tuple[int, int, int, int]:
        try:
            return (
                self.root.winfo_rootx(),
                self.root.winfo_rooty(),
                self.root.winfo_width(),
                self.root.winfo_height(),
            )
        except tk.TclError:
            return (0, 0, 0, 0)

    async def cleanup(self) -> None:
        if tk is None:
            return
        self._detach_logging_handler()
        try:
            self._cancel_resize_callback()
            self._cancel_geometry_save_handle(flush=True)
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

        self._cancel_geometry_save_handle(flush=True)

    @property
    def window_duration_ms(self) -> float:
        return self._window_duration_ms

    # ------------------------------------------------------------------
    # Geometry helpers

    def _current_geometry_string(self, event=None) -> Optional[str]:
        if tk is None:
            return None
        try:
            geometry = self.root.winfo_geometry()
        except tk.TclError:
            return None
        geometry = str(geometry).strip()
        return geometry or None

    def _on_configure(self, event) -> None:
        if event.widget is not self.root:
            return
        self._mark_resize_active()
        geometry = self._current_geometry_string(event)
        log_method = self.logger.info if not self._logged_first_configure else self.logger.debug
        log_method(
            "<Configure> root event: geom=%s size=%dx%d pos=%dx%d",
            geometry,
            getattr(event, 'width', -1),
            getattr(event, 'height', -1),
            getattr(event, 'x', -1),
            getattr(event, 'y', -1),
        )
        self._logged_first_configure = True
        if not geometry or geometry == self._last_geometry:
            return
        self._last_geometry = geometry
        updated = self.model.set_window_geometry(geometry)
        if updated or self.model.has_pending_window_geometry():
            self._schedule_geometry_persist()

    def _schedule_geometry_persist(self, delay: Optional[float] = None) -> None:
        if self._event_loop is None:
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                return
        self._cancel_geometry_save_handle()

        def callback() -> None:
            self._geometry_save_handle = None
            if self.model.has_pending_window_geometry():
                try:
                    self._event_loop.create_task(self.model.persist_window_geometry())
                except RuntimeError:
                    self.logger.debug("Event loop unavailable for geometry persist")

        effective_delay = self._geometry_save_delay if delay is None else delay

        if effective_delay <= 0:
            callback()
        else:
            self._geometry_save_handle = self._event_loop.call_later(effective_delay, callback)

    def _cancel_geometry_save_handle(self, flush: bool = False) -> None:
        if self._geometry_save_handle:
            self._geometry_save_handle.cancel()
            self._geometry_save_handle = None
        if flush and self._event_loop and self.model.has_pending_window_geometry():
            try:
                self._event_loop.create_task(self.model.persist_window_geometry())
            except RuntimeError:
                self.logger.debug("Event loop unavailable during geometry flush")

    def _cancel_resize_callback(self) -> None:
        handle = self._resize_reset_handle
        if handle is None:
            return
        try:
            self.root.after_cancel(handle)
        except tk.TclError:
            pass
        finally:
            self._resize_reset_handle = None

    def _mark_resize_active(self) -> None:
        self._resize_active = True
        self._cancel_resize_callback()
        delay_ms = max(10, int(self._resize_idle_delay * 1000))
        try:
            self._resize_reset_handle = self.root.after(delay_ms, self._clear_resize_flag)
        except tk.TclError:
            self._resize_reset_handle = None

    def _clear_resize_flag(self) -> None:
        self._resize_reset_handle = None
        self._resize_active = False

    def is_resizing(self) -> bool:
        return bool(self._resize_active)
