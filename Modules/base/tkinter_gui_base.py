
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import tkinter as tk

logger = logging.getLogger(__name__)


class TkinterGUIBase:

    def get_geometry(self) -> str:
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")
        return self.root.geometry()

    def initialize_gui_framework(
        self,
        title: str,
        default_width: int,
        default_height: int,
        on_closing_callback: Optional[callable] = None,
        menu_bar_kwargs: Optional[dict] = None
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

        # Step 1: Create root window
        self.root = tk.Tk()

        # Step 2: Set window title
        self.root.title(title)

        # Step 3: Initialize window geometry
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
            self.root.protocol("WM_DELETE_WINDOW", callback)
        else:
            logger.warning("No window close callback provided")

        logger.info("GUI framework initialized: %s", title)

    def initialize_window_geometry(self, default_width: int, default_height: int):
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")
        if not hasattr(self, 'args'):
            raise AttributeError("TkinterGUIBase requires 'self.args' attribute")

        if hasattr(self.args, 'window_geometry') and self.args.window_geometry:
            self.root.geometry(self.args.window_geometry)
            logger.info("Applied window geometry from master: %s", self.args.window_geometry)
        else:
            self.root.geometry(f"{default_width}x{default_height}")
            logger.debug("Applied default window geometry: %dx%d", default_width, default_height)


    def create_standard_layout(self, logger_height: int = 3, content_title: str = "Module"):
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
        main_frame.rowconfigure(1, weight=0)  # Logger (fixed)

        self.module_content_frame = ttk.LabelFrame(main_frame, text=content_title, padding="3")
        self.module_content_frame.grid(row=0, column=0, sticky='nsew', pady=(0, 5))

        self.log_frame = self.create_logger_display(main_frame, height=logger_height)
        self.log_frame.grid(row=1, column=0, sticky='ew')

        config_key = "gui_show_" + re.sub(r'[^a-zA-Z0-9]+', '_', content_title.lower()).strip('_')
        toggle_label = f"Show {content_title}"

        if hasattr(self, 'add_view_toggle'):
            self.module_content_visible_var = self.add_view_toggle(
                toggle_label,
                self.module_content_frame,
                config_key,
                default_visible=True
            )

        return self.module_content_frame

    def create_logger_display(self, parent_frame, height: int = 3):
        import tkinter as tk
        from tkinter import ttk, scrolledtext
        import logging

        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")

        self.log_frame = ttk.LabelFrame(parent_frame, text="Logger", padding="3")

        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=0)

        self.log_text = scrolledtext.ScrolledText(
            self.log_frame,
            height=height,
            wrap=tk.WORD,
            bg='#f5f5f5',
            fg='#333333'
        )
        self.log_text.grid(row=0, column=0, sticky='ew')
        self.log_text.config(state='disabled')  # Read-only

        self._setup_log_handler()

        return self.log_frame

    def _setup_log_handler(self):
        import tkinter as tk
        import logging

        class TextHandler(logging.Handler):

            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
                self.setFormatter(
                    logging.Formatter(
                        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        datefmt='%H:%M:%S'
                    )
                )

            def emit(self, record):
                msg = self.format(record) + '\n'
                self.text_widget.after(0, self._append_log, msg)

            def _append_log(self, msg):
                self.text_widget.config(state='normal')
                self.text_widget.insert(tk.END, msg)
                self.text_widget.see(tk.END)  # Auto-scroll
                lines = int(self.text_widget.index('end-1c').split('.')[0])
                if lines > 500:
                    self.text_widget.delete('1.0', f'{lines-500}.0')
                self.text_widget.config(state='disabled')

        text_handler = TextHandler(self.log_text)
        text_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(text_handler)
        self.log_handler = text_handler

    def save_window_geometry_to_config(self):
        raise NotImplementedError(
            "Subclasses must override save_window_geometry_to_config() "
            "to provide their own __file__ path for config calculation"
        )

    def send_geometry_to_parent(self):
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")

        from Modules.base import gui_utils
        gui_utils.send_geometry_to_parent(self.root)

    def send_quitting_status(self):
        try:
            from logger_core.commands import StatusMessage
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

        try:
            self.root.destroy()
        except Exception as e:
            logger.debug("Error destroying window: %s", e)

    def handle_window_close(self):
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterGUIBase requires 'self.root' attribute")
        if not hasattr(self, 'system'):
            raise AttributeError("TkinterGUIBase requires 'self.system' attribute")

        logger.info("=" * 60)
        logger.info("HANDLE_WINDOW_CLOSE: Starting close sequence")
        current_geometry = self.root.geometry()
        logger.info("HANDLE_WINDOW_CLOSE: Current window geometry: %s", current_geometry)

        logger.info("HANDLE_WINDOW_CLOSE: Step 1 - Saving geometry to local config...")
        try:
            self.save_window_geometry_to_config()
            logger.info("HANDLE_WINDOW_CLOSE: Step 1 - ✓ Saved to local config")
        except Exception as e:
            logger.error("HANDLE_WINDOW_CLOSE: Step 1 - ✗ Failed to save: %s", e, exc_info=True)

        # Send final geometry to parent before quitting (for master logger mode)
        logger.info("HANDLE_WINDOW_CLOSE: Step 2 - Sending geometry to parent...")
        try:
            self.send_geometry_to_parent()
            logger.info("HANDLE_WINDOW_CLOSE: Step 2 - ✓ Sent to parent")
        except Exception as e:
            logger.error("HANDLE_WINDOW_CLOSE: Step 2 - ✗ Failed to send: %s", e, exc_info=True)

        logger.info("HANDLE_WINDOW_CLOSE: Step 3 - Sending quitting status...")
        self.send_quitting_status()

        logger.info("HANDLE_WINDOW_CLOSE: Step 4 - Withdrawing window...")
        self.withdraw_window()

        logger.info("HANDLE_WINDOW_CLOSE: Step 5 - Setting shutdown flags...")
        self.system.running = False
        self.system.shutdown_event.set()

        logger.info("HANDLE_WINDOW_CLOSE: Step 6 - Quitting tkinter...")
        try:
            self.root.quit()
            logger.info("HANDLE_WINDOW_CLOSE: ✓ Close sequence completed")
        except Exception as e:
            logger.error("HANDLE_WINDOW_CLOSE: Error quitting tkinter: %s", e)
        logger.info("=" * 60)
