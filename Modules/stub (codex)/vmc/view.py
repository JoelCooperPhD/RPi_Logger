"""View component responsible for the interactive placeholder window."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

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
from .constants import DISPLAY_NAME, PLACEHOLDER_GEOMETRY

logger = logging.getLogger(__name__)

class StubCodexView:
    """Tkinter view that mirrors model state and forwards user intent."""

    def __init__(
        self,
        args,
        model: StubCodexModel,
        action_callback: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> None:
        start = time.perf_counter()

        self.args = args
        self.model = model
        self.action_callback = action_callback
        self._close_requested = False
        self._window_duration_ms: float = 0.0
        self._loop_running = False
        self._log_handler: Optional[logging.Handler] = None
        self._last_geometry: Optional[str] = None
        self._geometry_save_handle: Optional[asyncio.Handle] = None
        self._geometry_save_delay = 0.25
        self.io_view_frame: Optional[ttk.LabelFrame] = None
        self.io_view_visible_var: Optional[tk.BooleanVar] = None
        self.io_text: Optional[scrolledtext.ScrolledText] = None

        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - defensive
            self._event_loop = None

        if tk is None or ttk is None or scrolledtext is None:
            raise RuntimeError(f"tkinter unavailable: {TK_IMPORT_ERROR}")

        self.root = tk.Tk()
        self.root.title(DISPLAY_NAME)

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
        logger.info("StubCodexView initialized in %.2f ms", elapsed)

    # ------------------------------------------------------------------
    # UI construction

    def _build_ui(self) -> None:
        assert tk is not None and ttk is not None and scrolledtext is not None

        self.io_view_visible_var = tk.BooleanVar(value=True)
        self.log_visible_var = tk.BooleanVar(value=True)

        self._create_menu_bar()

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.root, padding="12")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=0)
        main_frame.rowconfigure(2, weight=0)

        stub_frame = ttk.LabelFrame(main_frame, text="Stub", padding="10")
        stub_frame.grid(row=0, column=0, sticky="nsew")
        stub_frame.columnconfigure(0, weight=1)
        stub_frame.rowconfigure(0, weight=1)

        self.io_view_frame = ttk.LabelFrame(main_frame, text="IO Stub", padding="8")
        self.io_view_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.io_view_frame.columnconfigure(0, weight=1)
        self.io_view_frame.rowconfigure(0, weight=1)

        self.io_text = scrolledtext.ScrolledText(
            self.io_view_frame,
            height=2,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#f5f5f5",
            fg="#333333",
        )
        self.io_text.grid(row=0, column=0, sticky="nsew")
        self._set_io_placeholder()

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

    def _create_menu_bar(self) -> None:
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Log File", command=self._open_log_file)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_quit_clicked)

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

    # ------------------------------------------------------------------
    # IO view helpers

    def _toggle_io_view(self) -> None:
        if not self.io_view_frame or not self.io_view_visible_var:
            return
        if self.io_view_visible_var.get():
            self.io_view_frame.grid()
        else:
            self.io_view_frame.grid_remove()

    def _set_io_placeholder(self) -> None:
        if not self.io_text:
            return
        self.io_text.config(state=tk.NORMAL)
        self.io_text.delete('1.0', tk.END)
        self.io_text.insert('1.0', 'IO telemetry will appear here.\n')
        self.io_text.config(state=tk.DISABLED)

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
        if not self.log_frame:
            return
        if self.log_visible_var.get():
            self.log_frame.grid()
        else:
            self.log_frame.grid_remove()

    def _open_log_file(self) -> None:
        log_file = self._resolve_log_file()
        if log_file is None:
            logger.warning("Log file path unavailable yet")
            return
        if not log_file.exists():
            logger.warning("Log file does not exist: %s", log_file)
            return

        try:
            if sys.platform.startswith('linux'):
                subprocess.Popen(['xdg-open', str(log_file)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(log_file)])
            elif sys.platform == 'win32':
                subprocess.Popen(['notepad.exe', str(log_file)])
            else:
                logger.warning("Unsupported platform for opening files: %s", sys.platform)
        except Exception as exc:
            logger.error("Failed to open log file: %s", exc)

    def _show_help(self) -> None:
        try:
            from logger_core.ui.help_dialogs import QuickStartDialog
            QuickStartDialog(self.root)
        except Exception as exc:
            logger.error("Failed to open help dialog: %s", exc)

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
        logger.debug("Model change: %s -> %s", prop, value)

    # ------------------------------------------------------------------
    # Lifecycle

    async def run(self) -> float:
        logger.info("StubCodexView run loop starting")
        if self._loop_running:
            return 0.0
        self._loop_running = True
        open_time = time.perf_counter()
        try:
            while not self._close_requested:
                try:
                    self.root.update()
                except tk.TclError:
                    break
                await asyncio.sleep(0.01)
        finally:
            self._window_duration_ms = max(0.0, (time.perf_counter() - open_time) * 1000.0)
            self._loop_running = False
            logger.info("StubCodexView run loop finished (%.2f ms)", self._window_duration_ms)
        return self._window_duration_ms

    def get_geometry(self) -> tuple[int, int, int, int]:
        self.root.update_idletasks()
        return (
            self.root.winfo_rootx(),
            self.root.winfo_rooty(),
            self.root.winfo_width(),
            self.root.winfo_height(),
        )

    async def cleanup(self) -> None:
        if tk is None:
            return
        self._detach_logging_handler()
        try:
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
            self.root.update_idletasks()
            # geometry() returns screen-relative coordinates that already
            # factor in window manager decorations (title bar, task bar, etc.).
            # Using the raw winfo_* values drifts the saved Y position by
            # the decoration height on every restart.
            geometry = self.root.geometry()
        except tk.TclError:
            return None
        geometry = str(geometry).strip()
        return geometry or None

    def _on_configure(self, event) -> None:
        if event.widget is not self.root:
            return
        geometry = self._current_geometry_string(event)
        if not geometry or geometry == self._last_geometry:
            return
        self._last_geometry = geometry
        updated = self.model.set_window_geometry(geometry)
        if updated or self.model.has_pending_window_geometry():
            self._schedule_geometry_persist()

    def _schedule_geometry_persist(self, delay: Optional[float] = None) -> None:
        if self._event_loop is None:
            return
        self._cancel_geometry_save_handle()

        def callback() -> None:
            self._geometry_save_handle = None
            if self.model.has_pending_window_geometry():
                try:
                    self._event_loop.create_task(self.model.persist_window_geometry())
                except RuntimeError:
                    logger.debug("Event loop unavailable for geometry persist")

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
                logger.debug("Event loop unavailable during geometry flush")
