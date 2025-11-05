import asyncio
import logging
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Modules.base import TkinterGUIBase, TkinterMenuBase

from ..model import StubModel

logger = logging.getLogger(__name__)


class StubView(TkinterGUIBase, TkinterMenuBase):
    def __init__(
        self,
        model: StubModel,
        args,
        window_geometry: Optional[str] = None
    ):
        self.model = model
        self.args = args
        self._close_requested = False

        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        self.root = tk.Tk()
        self.root.title("stub (claude)")

        if window_geometry:
            if isinstance(window_geometry, str):
                self.root.geometry(window_geometry)
            else:
                self.root.geometry(window_geometry.to_geometry_string())
        else:
            self.root.geometry("700x600")

        self._create_menu_and_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._last_geometry: Optional[str] = None
        self._shutting_down = False
        self._geometry_save_handle: Optional[asyncio.Handle] = None
        self._geometry_save_delay = 0.5
        self.root.bind("<Configure>", self._on_window_configure)

        logger.info("StubView initialized")

    def _create_menu_and_ui(self):
        self.create_menu_bar(include_sources=False)
        self._build_ui()

    def populate_module_menus(self):
        pass

    def get_output_directory(self) -> Path:
        return Path(self.args.output_dir) if hasattr(self.args, 'output_dir') else Path.cwd()

    def get_log_file(self) -> Path:
        return Path(self.args.log_file) if hasattr(self.args, 'log_file') else Path("logs/stub.log")

    def _build_ui(self) -> None:
        stub_frame = self.create_standard_layout(logger_height=2, content_title="Stub")
        stub_frame.columnconfigure(0, weight=1)
        stub_frame.rowconfigure(0, weight=1)

        ttk.Label(
            stub_frame,
            text="No module controls available for this stub.",
            anchor='center'
        ).grid(row=0, column=0, sticky='nsew', padx=10, pady=10)

        io_frame = self.create_io_view_frame(title="IO Stub", default_visible=True)
        if io_frame is not None:
            io_frame.columnconfigure(0, weight=1)
            io_frame.rowconfigure(0, weight=1)
            self.create_io_text_widget(height=2)

        self._apply_logger_visibility()

    def _on_window_configure(self, event):
        if event.widget != self.root or self._shutting_down:
            return

        try:
            geometry = self._get_current_geometry_string()
            if not geometry or geometry == self._last_geometry:
                return

            self._last_geometry = geometry
            updated = self.model.set_geometry(geometry)

            if updated or self.model.has_pending_geometry():
                self._schedule_geometry_save()

        except Exception as e:
            logger.debug(f"Error in configure event: {e}")

    def _get_current_geometry_string(self) -> Optional[str]:
        try:
            self.root.update_idletasks()
            return self.root.geometry()
        except tk.TclError:
            return None

    def _schedule_geometry_save(self, delay: Optional[float] = None) -> None:
        if self._event_loop is None:
            return

        self._cancel_geometry_save_handle()

        def callback() -> None:
            self._geometry_save_handle = None
            if self.model.has_pending_geometry():
                try:
                    self._event_loop.create_task(self._save_geometry_async())
                except RuntimeError:
                    logger.debug("Event loop unavailable for geometry save")

        effective_delay = self._geometry_save_delay if delay is None else delay

        if effective_delay <= 0:
            callback()
        else:
            self._geometry_save_handle = self._event_loop.call_later(effective_delay, callback)

    def _cancel_geometry_save_handle(self, flush: bool = False) -> None:
        if self._geometry_save_handle:
            self._geometry_save_handle.cancel()
            self._geometry_save_handle = None

        if flush and self._event_loop and self.model.has_pending_geometry():
            try:
                self._event_loop.create_task(self._save_geometry_async())
            except RuntimeError:
                logger.debug("Event loop unavailable during geometry flush")

    def _on_close(self):
        logger.info("Window close requested by user")
        self._shutting_down = True
        self._cancel_geometry_save_handle(flush=True)
        self._close_requested = True
        self.model.request_shutdown("window closed by user")
        self.root.quit()

    async def run(self):
        logger.info("StubView run() started - using manual async loop")
        while not self._close_requested:
            try:
                self.root.update()
                await asyncio.sleep(0.01)
            except tk.TclError as e:
                logger.debug(f"TclError (likely shutdown): {e}")
                break
            except Exception as e:
                logger.error(f"Error in GUI loop: {e}", exc_info=True)
                break
        logger.info("StubView run() ended")

    def get_geometry(self) -> tuple[int, int, int, int]:
        self.root.update_idletasks()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        return (x, y, width, height)

    async def cleanup(self):
        logger.info("StubView cleanup started")
        try:
            self._cancel_geometry_save_handle(flush=True)
            self.root.quit()
            self.root.destroy()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        logger.info("StubView cleanup complete")

    async def _save_geometry_async(self):
        try:
            from Modules.base import ConfigLoader

            geometry = self.model._pending_geometry
            if not geometry:
                return

            config_path = Path(__file__).parent.parent.parent / "config.txt"

            updates = {"window_geometry": geometry}

            success = await ConfigLoader.update_config_values_async(config_path, updates)
            if success:
                self.model.mark_geometry_saved(geometry)
                logger.debug(f"Saved window geometry: {geometry}")
            else:
                logger.warning("Failed to save window geometry to config")

        except Exception as e:
            logger.error(f"Error saving window geometry: {e}", exc_info=True)
