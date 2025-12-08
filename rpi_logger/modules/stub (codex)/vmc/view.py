"""View component responsible for the interactive placeholder window."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

from rpi_logger.core.logging_utils import get_module_logger

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
from rpi_logger.core.ui.theme.styles import Theme

_BASE_LOGGER = get_module_logger(__name__)
PREF_SHOW_IO_PANEL = "view.show_io_panel"
PREF_SHOW_LOGGER = "view.show_logger"

# Geometry helpers local to the stub to avoid depending on other modules.
_BOTTOM_MARGIN_ENV = "RPILOGGER_BOTTOM_UI_MARGIN"
try:
    SCREEN_BOTTOM_RESERVED = max(0, int(os.environ.get(_BOTTOM_MARGIN_ENV, "48")))
except ValueError:
    SCREEN_BOTTOM_RESERVED = 48


def _parse_geometry_string(geometry_str: str) -> Optional[tuple[int, int, int, int]]:
    """Parse a Tk geometry string into (width, height, x, y)."""
    try:
        match = re.match(r"(\d+)x(\d+)([\+\-]\d+)([\+\-]\d+)", geometry_str)
        if not match:
            _BASE_LOGGER.error("Failed to parse geometry string: '%s'", geometry_str)
            return None
        width = int(match.group(1))
        height = int(match.group(2))
        x = int(match.group(3))
        y = int(match.group(4))
        return width, height, x, y
    except Exception as exc:  # pragma: no cover - defensive
        _BASE_LOGGER.error("Exception parsing geometry string '%s': %s", geometry_str, exc)
        return None


def _format_geometry_string(width: int, height: int, x: int, y: int) -> str:
    """Format geometry values into a Tk geometry string."""
    return f"{width}x{height}+{x}+{y}"


def _clamp_geometry_to_screen(
    width: int,
    height: int,
    x: int,
    y: int,
    *,
    screen_height: Optional[int] = None,
) -> tuple[int, int, int, int]:
    """Clamp geometry so window bottom stays above the reserved screen area.

    This prevents windows from being positioned under the RPi taskbar.
    Uses raw Tk coordinates - no title bar offset adjustments.
    """
    width = int(width)
    height = int(height)
    x = int(x)
    y = int(y)

    if screen_height is not None and screen_height > 0:
        bottom_limit = max(0, screen_height - SCREEN_BOTTOM_RESERVED)
        max_y = max(0, bottom_limit - height)
        if y > max_y:
            _BASE_LOGGER.debug(
                "Clamping window to visible region (screen=%d, reserve=%d, height=%d, y=%d->%d)",
                screen_height, SCREEN_BOTTOM_RESERVED, height, y, max_y,
            )
            y = max_y

    return width, height, x, y

class StubCodexView:
    """Tkinter view that mirrors model state and forwards user intent."""

    def __init__(
        self,
        args,
        model: StubCodexModel,
        action_callback: Optional[Callable[..., Awaitable[None]]] = None,
        *,
        display_name: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        start = time.perf_counter()

        self.args = args
        self.model = model
        self.action_callback = action_callback
        self.display_name = display_name
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
        self.stub_frame: Optional[ttk.Frame] = None
        self._resize_active = False
        self._resize_reset_handle: Optional[str] = None
        self._resize_idle_delay = 0.15
        self._logged_first_configure = False
        self._main_frame: Optional[ttk.Frame] = None
        self._io_row_index = 1
        self._help_menu_label = "Help"
        self.help_menu: Optional[tk.Menu] = None

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

        # Clamp initial geometry to screen bounds (keeps window above taskbar)
        initial_geometry = self._current_geometry_string()
        clamped_geometry = self._clamp_geometry_string(initial_geometry)
        if clamped_geometry and clamped_geometry != initial_geometry:
            try:
                self.root.geometry(clamped_geometry)
                self.logger.debug("Clamped initial geometry to screen bounds: %s -> %s", initial_geometry, clamped_geometry)
            except tk.TclError:
                pass
        self._last_geometry = clamped_geometry or initial_geometry
        self.root.bind("<Configure>", self._on_configure)

        elapsed = (time.perf_counter() - start) * 1000.0
        self.logger.info("StubCodexView initialized in %.2f ms", elapsed)

    # ------------------------------------------------------------------
    # UI construction

    def _build_ui(self) -> None:
        assert tk is not None and ttk is not None and scrolledtext is not None

        # Apply the theme to the root window
        Theme.apply(self.root)

        io_visible = self.model.get_preference_bool(
            PREF_SHOW_IO_PANEL,
            True,
            fallback_keys=("gui_io_stub_visible",),
        )

        self.io_view_visible_var = tk.BooleanVar(value=io_visible)

        log_visible = self.model.get_preference_bool(
            PREF_SHOW_LOGGER,
            True,
            fallback_keys=("gui_logger_visible",),
        )

        self.log_visible_var = tk.BooleanVar(value=log_visible)

        self.menubar: Optional[tk.Menu] = None
        self.view_menu: Optional[tk.Menu] = None
        self._create_menu_bar()

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.root, padding="12")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(self._io_row_index, weight=0)
        main_frame.rowconfigure(2, weight=0)
        self._main_frame = main_frame

        self.stub_frame = ttk.Frame(main_frame, padding="0")
        self.stub_frame.grid(row=0, column=0, sticky="nsew")
        self.logger.info("Stub frame added to main layout")

        self.io_view_frame = ttk.LabelFrame(main_frame, text="Capture Stats", padding="8")
        self.io_view_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.io_view_frame.columnconfigure(0, weight=1)
        self.io_view_frame.rowconfigure(0, weight=1)
        self._set_io_row_visible(True)

        self.log_frame = ttk.LabelFrame(main_frame, text="Logger", padding="8")
        self.log_frame.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            self.log_frame,
            height=4,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        Theme.configure_scrolled_text(self.log_text, readonly=True)

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

    def set_preview_title(self, title: str) -> None:
        """No-op since stub_frame is now a plain Frame without a label."""
        pass

    def set_window_title(self, title: str) -> None:
        """Update the main window title."""
        try:
            self.root.title(title)
        except tk.TclError:
            pass

    def _create_menu_bar(self) -> None:
        menubar = tk.Menu(self.root)
        Theme.configure_menu(menubar)
        self.root.config(menu=menubar)
        self.menubar = menubar

        file_menu = tk.Menu(menubar, tearoff=0)
        Theme.configure_menu(file_menu)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Log File", command=self._open_log_file)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_quit_clicked)

        view_menu = tk.Menu(menubar, tearoff=0)
        Theme.configure_menu(view_menu)
        self.view_menu = view_menu
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_checkbutton(
            label="Show Capture Stats",
            variable=self.io_view_visible_var,
            command=self._toggle_io_view,
        )
        view_menu.add_checkbutton(
            label="Show Logger",
            variable=self.log_visible_var,
            command=self._toggle_log_visibility,
        )

        help_menu = tk.Menu(menubar, tearoff=0)
        Theme.configure_menu(help_menu)
        menubar.add_cascade(label=self._help_menu_label, menu=help_menu)
        help_menu.add_command(label="Quick Start Guide", command=self._show_help)
        self.help_menu = help_menu

    def add_menu(self, label: str, *, tearoff: int = 0) -> Optional[tk.Menu]:
        if self.menubar is None:
            return None
        menu = tk.Menu(self.menubar, tearoff=tearoff)
        Theme.configure_menu(menu)
        help_index = None
        if self.help_menu is not None and label != self._help_menu_label:
            help_index = self._find_menu_index(self._help_menu_label)
        try:
            if help_index is None:
                self.menubar.add_cascade(label=label, menu=menu)
            else:
                self.menubar.insert_cascade(help_index, label=label, menu=menu)
        except tk.TclError:
            return None
        return menu

    def add_view_submenu(self, label: str, *, tearoff: int = 0) -> Optional[tk.Menu]:
        if self.view_menu is None:
            return None
        submenu = tk.Menu(self.view_menu, tearoff=tearoff)
        Theme.configure_menu(submenu)
        self.view_menu.add_cascade(label=label, menu=submenu)
        return submenu

    def _find_menu_index(self, label: str) -> Optional[int]:
        if self.menubar is None:
            return None
        try:
            end_index = self.menubar.index("end")
        except tk.TclError:
            return None
        if end_index is None:
            return None
        for index in range(end_index + 1):
            try:
                entry_label = self.menubar.entrycget(index, "label")
            except tk.TclError:
                continue
            if entry_label == label:
                return index
        return None

    # ------------------------------------------------------------------
    # IO view helpers

    def build_io_stub_content(self, builder: Callable[[tk.Widget], None]) -> None:
        """Replace the IO stub frame contents using the provided builder."""

        if self.io_view_frame is None:
            return

        for child in list(self.io_view_frame.winfo_children()):
            child.destroy()

        builder(self.io_view_frame)

        try:
            self.io_view_frame.update_idletasks()
        except tk.TclError:
            pass

    def clear_io_stub_content(self) -> None:
        if self.io_view_frame is None:
            return
        for child in list(self.io_view_frame.winfo_children()):
            child.destroy()

    def set_io_stub_title(self, title: str) -> None:
        if self.io_view_frame is None:
            return
        try:
            self.io_view_frame.config(text=title)
        except tk.TclError:
            pass

    def _toggle_io_view(self) -> None:
        if not self.io_view_frame or not self.io_view_visible_var:
            return
        visible = self.io_view_visible_var.get()
        if visible:
            self.io_view_frame.grid()
            self._set_io_row_visible(True)
        else:
            self.io_view_frame.grid_remove()
            self._set_io_row_visible(False)

        if self._event_loop and hasattr(self.model, 'persist_preferences'):
            self._event_loop.create_task(
                self.model.persist_preferences({PREF_SHOW_IO_PANEL: visible})
            )

    def show_io_stub(self) -> None:
        if not self.io_view_frame or not self.io_view_visible_var:
            return
        self.io_view_visible_var.set(True)
        self.io_view_frame.grid()
        self._set_io_row_visible(True)

    def hide_io_stub(self) -> None:
        if not self.io_view_frame or not self.io_view_visible_var:
            return
        self.io_view_visible_var.set(False)
        self.io_view_frame.grid_remove()
        self._set_io_row_visible(False)

    def _set_io_row_visible(self, visible: bool) -> None:
        if self._main_frame is None:
            return
        minsize = 70 if visible else 0
        try:
            self._main_frame.rowconfigure(self._io_row_index, minsize=minsize)
        except tk.TclError:
            pass

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
        visible = self.log_visible_var.get()
        if visible:
            self.log_frame.grid()
        else:
            self.log_frame.grid_remove()

        if self._event_loop and hasattr(self.model, 'persist_preferences'):
            self._event_loop.create_task(
                self.model.persist_preferences({PREF_SHOW_LOGGER: visible})
            )

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
            from rpi_logger.core.ui.dialogs.quick_start import QuickStartDialog
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
        """Handle explicit quit from File menu - actually terminates."""
        self.request_quit()

    def _on_close(self) -> None:
        """Handle window close (X button) - quit the module.

        When the user clicks X, the module should terminate and notify
        the main logger so the UI toggle can be updated.
        """
        self.logger.info("Window close requested - quitting module")
        self.request_quit()

    def show_window(self) -> None:
        """Show the window if it was hidden."""
        self.logger.info("Showing window")
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass
        # Notify main logger that window was shown via status message
        from rpi_logger.core.commands.command_protocol import StatusMessage
        StatusMessage.send("window_shown")

    def hide_window(self) -> None:
        """Hide the window without terminating the process."""
        self.logger.info("Hiding window")
        self._cancel_geometry_save_handle(flush=True)
        try:
            self.root.withdraw()
        except tk.TclError:
            pass
        # Notify main logger that window was hidden via status message
        from rpi_logger.core.commands.command_protocol import StatusMessage
        StatusMessage.send("window_hidden")

    def is_window_visible(self) -> bool:
        """Return True if window is currently visible."""
        try:
            return self.root.winfo_viewable()
        except tk.TclError:
            return False

    def request_quit(self) -> None:
        """Actually quit the application (called when module is deactivated)."""
        if self._close_requested:
            return
        self._close_requested = True
        self.logger.info("Quit requested - terminating")
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
        # Clamp to screen bounds, store raw Tk coordinates
        clamped_geometry = self._clamp_geometry_string(geometry)
        if not clamped_geometry or clamped_geometry == self._last_geometry:
            return
        self._last_geometry = clamped_geometry
        updated = self.model.set_window_geometry(clamped_geometry)
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

    def _clamp_geometry_string(self, geometry: Optional[str]) -> Optional[str]:
        """Clamp geometry string to keep window within screen bounds."""
        if not geometry:
            return None

        parsed = _parse_geometry_string(geometry)
        if not parsed:
            return None

        width, height, x, y = parsed
        width, height, x, y = _clamp_geometry_to_screen(
            width, height, x, y,
            screen_height=self._get_screen_height(),
        )
        return _format_geometry_string(width, height, x, y)

    def _get_screen_height(self) -> Optional[int]:
        if tk is None:
            return None
        try:
            return int(self.root.winfo_screenheight())
        except tk.TclError:
            return None
