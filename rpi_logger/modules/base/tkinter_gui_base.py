
import logging
import re
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rpi_logger.core.logging_utils import get_module_logger

if TYPE_CHECKING:
    import tkinter as tk

logger = get_module_logger(__name__)


class TkinterGUIBase:

    def get_geometry(self) -> str:
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")
        target = getattr(self.root, "geometry", None)
        if callable(target):
            return target()
        resolver = getattr(self.root, "winfo_toplevel", None)
        if callable(resolver):
            try:
                window = resolver()
            except Exception as exc:  # pragma: no cover - defensive guard
                raise AttributeError("Unable to resolve window geometry for embedded GUI") from exc
            geometry = getattr(window, "geometry", None)
            if callable(geometry):
                return geometry()
        raise AttributeError("TkinterGUIBase cannot determine geometry for this widget")

    def initialize_gui_framework(
        self,
        title: str,
        default_width: int,
        default_height: int,
        on_closing_callback: Optional[callable] = None,
        menu_bar_kwargs: Optional[dict] = None,
        master: Optional["tk.Widget"] = None,
    ):
        """
        Template method for GUI initialization.

        Consolidates common initialization pattern across all modules:
        1. Create Tk root window
        2. Set window title
        3. Initialize window geometry
        4. Create menu bar (if TkinterMenuBase is mixed in)
        5. Create widgets (calls _create_widgets() - subclass implements)
        6. Set window close protocol

        Args:
            title: Window title
            default_width: Default window width in pixels
            default_height: Default window height in pixels
            on_closing_callback: Callback for window close event (defaults to _on_closing)
            menu_bar_kwargs: Optional kwargs to pass to create_menu_bar()
        """
        import tkinter as tk

        if not hasattr(self, 'args'):
            raise AttributeError("GUI requires 'self.args' attribute to be set before calling initialize_gui_framework()")

        self._embedded_mode = master is not None
        # Step 1: Create or re-use root window
        self.root = master if master is not None else tk.Tk()

        # Step 2: Set window title when we own the toplevel
        if not self._embedded_mode:
            self.root.title(title)
        else:
            logger.debug("Embedded GUI '%s' mounted inside host container", title)

        # Step 3: Initialize window geometry for standalone windows only
        self.initialize_window_geometry(default_width, default_height)

        # Step 4: Create menu bar (if available from TkinterMenuBase)
        if hasattr(self, 'create_menu_bar'):
            kwargs = menu_bar_kwargs or {}
            self.create_menu_bar(**kwargs)

        # Step 5: Create module-specific widgets (subclass implements this)
        if hasattr(self, '_create_widgets'):
            self._create_widgets()
        else:
            logger.warning("GUI subclass should implement _create_widgets() method")

        # Step 6: Set window close protocol
        callback = on_closing_callback or (self._on_closing if hasattr(self, '_on_closing') else None)
        if callback:
            protocol_target = getattr(self.root, "protocol", None)
            target = self.root
            if not callable(protocol_target):
                resolver = getattr(self.root, "winfo_toplevel", None)
                if callable(resolver):
                    try:
                        target = resolver()
                        protocol_target = getattr(target, "protocol", None)
                    except Exception:
                        protocol_target = None
            if callable(protocol_target):
                try:
                    protocol_target("WM_DELETE_WINDOW", callback)
                except Exception:
                    logger.warning("Unable to bind WM_DELETE_WINDOW handler", exc_info=True)
            else:
                logger.debug("No WM protocol target available; close handler not bound")
        else:
            logger.warning("No window close callback provided")

        logger.info("GUI framework initialized: %s", title)

    def initialize_window_geometry(self, default_width: int, default_height: int):
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")
        if not hasattr(self, 'args'):
            raise AttributeError("TkinterGUIBase requires 'self.args' attribute")
        if getattr(self, "_embedded_mode", False):
            logger.debug("Embedded GUI inherits geometry from host window")
            return

        if hasattr(self.args, 'window_geometry') and self.args.window_geometry:
            self.root.geometry(self.args.window_geometry)
            logger.info("Applied window geometry from master: %s", self.args.window_geometry)
        else:
            self.root.geometry(f"{default_width}x{default_height}")
            logger.debug("Applied default window geometry: %dx%d", default_width, default_height)


    def create_standard_layout(self, logger_height: int = 4, content_title: str = "Module", enable_content_toggle: bool = True):
        from tkinter import ttk
        import re

        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")

        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.grid(row=0, column=0, sticky='nsew')
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)  # Module content (expandable)
        main_frame.rowconfigure(1, weight=0)  # Optional IO view (fixed)
        main_frame.rowconfigure(2, weight=0)  # Logger (fixed)

        self.module_content_frame = ttk.LabelFrame(main_frame, text=content_title, padding="3")
        self.module_content_frame.grid(row=0, column=0, sticky='nsew', pady=(0, 5))

        self.io_view_frame = None
        self.io_view_visible_var = None

        self.log_frame = self.create_logger_display(main_frame, height=logger_height)
        self.log_frame.grid(row=2, column=0, sticky='ew')

        if hasattr(self, 'logger_visible_var') and not self.logger_visible_var.get():
            self.log_frame.grid_remove()

        config_key = "gui_show_" + re.sub(r'[^a-zA-Z0-9]+', '_', content_title.lower()).strip('_')
        toggle_label = f"Show {content_title}"

        self.module_content_visible_var = None
        if enable_content_toggle and hasattr(self, 'add_view_toggle'):
            self.module_content_visible_var = self.add_view_toggle(
                toggle_label,
                self.module_content_frame,
                config_key,
                default_visible=True
            )

        return self.module_content_frame

    def create_io_view_frame(
        self,
        title: str = "IO Stub",
        *,
        default_visible: bool = False,
        menu_label: str | None = None,
        config_key: str | None = None,
        padding: str | tuple = "3",
    ):
        """Create an optional IO view frame above the logger and hook it into the View menu."""
        from tkinter import ttk

        if getattr(self, 'io_view_frame', None) is not None:
            return self.io_view_frame

        if not hasattr(self, 'log_frame') or self.log_frame is None:
            raise AttributeError("IO view requires logger frame to be initialized via create_standard_layout().")

        parent = self.log_frame.master
        if parent is None:
            raise AttributeError("IO view requires a grid-managed parent frame.")

        sanitized_title = re.sub(r'[^a-zA-Z0-9]+', '_', title.lower()).strip('_') or 'io_stub'
        if config_key is None:
            config_key = f"gui_show_{sanitized_title}"
        if menu_label is None:
            menu_label = f"Show {title}"

        self.io_view_frame = ttk.LabelFrame(parent, text=title, padding=padding)
        self.io_view_frame.columnconfigure(0, weight=1)
        self.io_view_frame.grid(row=1, column=0, sticky='ew', pady=(0, 5))
        parent.rowconfigure(1, weight=0)

        if hasattr(self, 'add_view_toggle'):
            self.io_view_visible_var = self.add_view_toggle(
                menu_label,
                self.io_view_frame,
                config_key,
                default_visible=default_visible,
            )
        else:
            self.io_view_visible_var = None
            if not default_visible:
                self.io_view_frame.grid_remove()

        return self.io_view_frame

    def set_io_view_title(self, title: str) -> None:
        """Update the IO view label text after creation."""
        if not getattr(self, 'io_view_frame', None):
            raise AttributeError("IO view frame has not been created.")
        self.io_view_frame.config(text=title)

    def create_io_text_widget(self, height: int = 2):
        """
        Create a ScrolledText widget for the IO view frame with styling matching the logger.
        Must be called after create_io_view_frame().

        Returns:
            ScrolledText widget configured with consistent styling
        """
        import tkinter as tk
        from tkinter import scrolledtext

        if not hasattr(self, 'io_view_frame') or self.io_view_frame is None:
            raise AttributeError("IO text widget requires io_view_frame to be created first via create_io_view_frame().")

        self.io_text = scrolledtext.ScrolledText(
            self.io_view_frame,
            height=height,
            wrap=tk.WORD
        )
        self.io_text.grid(row=0, column=0, sticky='nsew')
        from rpi_logger.core.ui.theme.styles import Theme
        Theme.configure_scrolled_text(self.io_text, readonly=True)

        return self.io_text

    def create_logger_display(self, parent_frame, height: int = 3):
        import tkinter as tk
        from tkinter import ttk, scrolledtext
        import logging

        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")

        self.log_frame = ttk.LabelFrame(parent_frame, text="Logger", padding="3")

        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            self.log_frame,
            height=height,
            wrap=tk.WORD
        )
        self.log_text.grid(row=0, column=0, sticky='nsew')
        from rpi_logger.core.ui.theme.styles import Theme
        Theme.configure_scrolled_text(self.log_text, readonly=True)

        self._setup_log_handler()

        return self.log_frame

    def _setup_log_handler(self):
        import tkinter as tk
        import logging

        class TextHandler(logging.Handler):

            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
                self._closed = False
                # Use a bounded deque to prevent unbounded memory growth
                # 100 pending callbacks is more than enough for normal operation
                self._pending_after_ids: deque[str] = deque(maxlen=100)
                self.setFormatter(
                    logging.Formatter(
                        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        datefmt='%H:%M:%S'
                    )
                )

            def emit(self, record):
                if self._closed:
                    return
                msg = self.format(record) + '\n'
                try:
                    after_id = self.text_widget.after(0, self._append_log, msg)
                    self._pending_after_ids.append(after_id)
                except (tk.TclError, RuntimeError):
                    # Widget is gone / Tk main loop already shut down
                    self._closed = True
                    return

            def _append_log(self, msg):
                if self._closed:
                    return
                try:
                    # Check if widget still exists
                    if not self.text_widget.winfo_exists():
                        self._closed = True
                        return
                    self.text_widget.config(state='normal')
                    self.text_widget.insert(tk.END, msg)
                    self.text_widget.see(tk.END)  # Auto-scroll
                    lines = int(self.text_widget.index('end-1c').split('.')[0])
                    if lines > 500:
                        self.text_widget.delete('1.0', f'{lines-500}.0')
                    self.text_widget.config(state='disabled')
                except (tk.TclError, RuntimeError):
                    # Widget destroyed or Tk shutting down
                    self._closed = True
                    return

            def close(self):
                self._closed = True
                # Cancel any pending after callbacks
                for after_id in self._pending_after_ids:
                    try:
                        self.text_widget.after_cancel(after_id)
                    except Exception:
                        pass
                self._pending_after_ids.clear()
                super().close()

        text_handler = TextHandler(self.log_text)
        text_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(text_handler)
        self.log_handler = text_handler

    def cleanup_log_handler(self):
        """Clean up the log handler and remove it from the root logger."""
        if hasattr(self, 'log_handler') and self.log_handler:
            self.log_handler.close()
            logging.getLogger().removeHandler(self.log_handler)
            self.log_handler = None

    def send_geometry_to_parent(self):
        """Send current window geometry to parent process for persistence."""
        if getattr(self, "_embedded_mode", False):
            logger.debug("Embedded GUI geometry managed by host; skipping send")
            return
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")

        from rpi_logger.modules.base import gui_utils

        # Get instance_id from args if available (for multi-instance modules)
        instance_id = None
        if hasattr(self, 'args') and hasattr(self.args, 'instance_id'):
            instance_id = self.args.instance_id

        gui_utils.send_geometry_to_parent(self.root, instance_id=instance_id)

    def send_quitting_status(self):
        try:
            from rpi_logger.core.commands import StatusMessage
            StatusMessage.send("quitting", {"reason": "user_closed_window"})
            logger.debug("Sent quitting status to parent")
        except Exception as e:
            logger.debug("Failed to send quitting status: %s", e)

    def withdraw_window(self):
        if not hasattr(self, 'root'):
            return

        try:
            self.root.withdraw()
        except Exception:
            pass

    def destroy_window(self):
        if not hasattr(self, 'root'):
            return

        # Clean up log handler before destroying window to prevent orphaned after callbacks
        self.cleanup_log_handler()

        try:
            self.root.destroy()
        except Exception as e:
            logger.debug("Error destroying window: %s", e)

    def handle_window_close(self):
        """Handle window close - send geometry to parent and signal quitting."""
        if getattr(self, "_embedded_mode", False):
            logger.debug("Embedded GUI close handled by host container")
            return
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")

        logger.info("Sending window geometry before shutdown")

        try:
            self.send_geometry_to_parent()
            logger.info("Sent geometry to parent")
        except Exception as e:
            logger.debug("Failed to send geometry to parent: %s", e)

        self.send_quitting_status()
