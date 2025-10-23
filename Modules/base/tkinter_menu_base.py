
import logging
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class TkinterMenuBase:

    def create_menu_bar(self, include_sources: bool = True, include_recording: bool = True):
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterMenuBase requires 'self.root' attribute")

        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        logger_visible_default = self.get_logger_visible_from_config()
        self.logger_visible_var = tk.BooleanVar(value=logger_visible_default)

        self._create_file_menu(menubar)

        if include_recording:
            self._create_recording_menu(menubar)

        if include_sources:
            self._create_sources_menu(menubar)

        self._create_view_menu(menubar)

        self.populate_module_menus()

        self._apply_logger_visibility()

    def _create_file_menu(self, menubar: tk.Menu):
        self.file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=self.file_menu)

        self.file_menu.add_command(
            label="Open Output Directory",
            command=self._on_open_output_dir
        )
        self.file_menu.add_separator()
        self.file_menu.add_command(
            label="Quit",
            command=self._on_quit
        )

    def _create_recording_menu(self, menubar: tk.Menu):
        self.recording_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Recording", menu=self.recording_menu)

        self.recording_menu.add_command(
            label="▶ Start Recording",
            command=lambda: self.on_start_recording()
        )
        self.recording_menu.add_command(
            label="⏹ Stop Recording",
            command=lambda: self.on_stop_recording()
        )

        self._recording_start_idx = 0
        self._recording_stop_idx = 1

    def _create_sources_menu(self, menubar: tk.Menu):
        self.sources_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Sources", menu=self.sources_menu)

    def _create_view_menu(self, menubar: tk.Menu):
        self.view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=self.view_menu)

        self.view_menu.add_checkbutton(
            label="Show Logger",
            variable=self.logger_visible_var,
            command=self._toggle_logger
        )


    def add_source_toggle(self, label: str, variable: tk.BooleanVar,
                         command: Callable) -> int:
        idx = self.sources_menu.index('end')
        if idx is None:
            idx = -1
        idx += 1

        self.sources_menu.add_checkbutton(
            label=label,
            variable=variable,
            command=command
        )
        return idx

    def add_view_option(self, label: str, variable: tk.BooleanVar,
                       command: Callable) -> int:
        idx = self.view_menu.index('end')
        if idx is None:
            idx = -1
        idx += 1

        self.view_menu.add_checkbutton(
            label=label,
            variable=variable,
            command=command
        )
        return idx

    def add_view_toggle(self, label: str, widget, config_key: str,
                       default_visible: bool = True) -> tk.BooleanVar:
        initial_state = self._load_view_state(config_key, default_visible)

        var = tk.BooleanVar(value=initial_state)

        def toggle():
            visible = var.get()
            if visible:
                widget.grid()
            else:
                widget.grid_remove()
            self._save_view_state(config_key, visible)

        self.add_view_option(label, var, toggle)

        if not initial_state:
            widget.grid_remove()

        return var

    def add_recording_action(self, label: str, command: Callable,
                            separator_before: bool = False) -> int:
        if separator_before:
            self.recording_menu.add_separator()

        idx = self.recording_menu.index('end')
        if idx is None:
            idx = -1
        idx += 1

        self.recording_menu.add_command(label=label, command=command)
        return idx

    def enable_recording_controls(self, enabled: bool):
        state = 'normal' if enabled else 'disabled'
        try:
            self.recording_menu.entryconfig(self._recording_start_idx, state=state)
            self.recording_menu.entryconfig(self._recording_stop_idx, state=state)
        except Exception as e:
            logger.debug("Error toggling recording menu: %s", e)

    def enable_sources_menu(self, enabled: bool):
        state = 'normal' if enabled else 'disabled'
        try:
            menu_size = self.sources_menu.index('end')
            if menu_size is not None:
                for i in range(menu_size + 1):
                    try:
                        self.sources_menu.entryconfig(i, state=state)
                    except Exception:
                        pass  # Skip invalid indices
        except Exception as e:
            logger.debug("Error toggling sources menu: %s", e)


    def populate_module_menus(self):
        pass

    def on_start_recording(self):
        raise NotImplementedError("Subclass must implement on_start_recording()")

    def on_stop_recording(self):
        raise NotImplementedError("Subclass must implement on_stop_recording()")

    def get_output_directory(self) -> Path:
        if hasattr(self, 'args') and hasattr(self.args, 'output_dir'):
            return self.args.output_dir
        if hasattr(self, 'system') and hasattr(self.system, 'session_dir'):
            return self.system.session_dir.parent
        raise NotImplementedError(
            "Subclass must implement get_output_directory() or provide args.output_dir"
        )


    def _load_view_state(self, config_key: str, default: bool) -> bool:
        if hasattr(self, 'system') and hasattr(self.system, 'config'):
            config = self.system.config
            if isinstance(config, dict):
                return config.get(config_key, default)
            else:
                return getattr(config, config_key, default)
        return default

    def _save_view_state(self, config_key: str, visible: bool):
        try:
            if hasattr(self, 'system') and hasattr(self.system, 'config'):
                config = self.system.config
                if isinstance(config, dict):
                    config[config_key] = visible
                else:
                    setattr(config, config_key, visible)

                if hasattr(self.system, 'config_file_path'):
                    from Modules.base import ConfigLoader
                    ConfigLoader.update_config_values(
                        self.system.config_file_path,
                        {config_key: visible}
                    )
                    logger.debug("Saved view state %s=%s to config", config_key, visible)
        except Exception as e:
            logger.error("Failed to save view state %s: %s", config_key, e)


    def get_logger_visible_from_config(self) -> bool:
        return self._load_view_state('gui_logger_visible', True)

    def _toggle_logger(self):
        visible = self.logger_visible_var.get()

        if hasattr(self, 'log_frame'):
            if visible:
                self.log_frame.grid()
                logger.info("Logger shown")
            else:
                self.log_frame.grid_remove()
                logger.info("Logger hidden")

        self._save_view_state('gui_logger_visible', visible)

    def _apply_logger_visibility(self):
        if hasattr(self, 'log_frame'):
            visible = self.logger_visible_var.get()
            if not visible:
                self.log_frame.grid_remove()


    def _on_open_output_dir(self):
        try:
            output_dir = self.get_output_directory()

            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(output_dir)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(output_dir)])
            elif sys.platform == 'win32':
                subprocess.Popen(['explorer', str(output_dir)])

            logger.info("Opened output directory: %s", output_dir)
        except Exception as e:
            logger.error("Failed to open output directory: %s", e)

    def _on_quit(self):
        if hasattr(self, 'handle_window_close'):
            self.handle_window_close()
        elif hasattr(self, '_on_closing'):
            self._on_closing()
        elif hasattr(self, 'on_closing'):
            self.on_closing()
        else:
            logger.warning("No close handler found, destroying window directly")
            if hasattr(self, 'root'):
                self.root.destroy()
