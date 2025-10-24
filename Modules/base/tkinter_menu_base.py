
import logging
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class TkinterMenuBase:

    def create_menu_bar(self, include_sources: bool = True):
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterMenuBase requires 'self.root' attribute")

        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        logger_visible_default = self.get_logger_visible_from_config()
        self.logger_visible_var = tk.BooleanVar(value=logger_visible_default)

        self._create_file_menu(menubar)

        if include_sources:
            self._create_sources_menu(menubar)

        self._create_view_menu(menubar)

        self._create_help_menu(menubar)

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

    def _create_help_menu(self, menubar: tk.Menu):
        self.help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=self.help_menu)

        self.help_menu.add_command(
            label="Quick Start Guide",
            command=self._show_help
        )

        self.help_menu.add_separator()

        self.help_menu.add_command(
            label="About RED Scientific",
            command=self._show_about
        )

        self.help_menu.add_command(
            label="System Information",
            command=self._show_system_info
        )

        self.help_menu.add_separator()

        self.help_menu.add_command(
            label="Open Logs Directory",
            command=self._open_logs_directory
        )

        self.help_menu.add_separator()

        self.help_menu.add_command(
            label="View Config File",
            command=self._open_config_file
        )

        self.help_menu.add_command(
            label="Reset Settings",
            command=self._reset_settings
        )

        self.help_menu.add_separator()

        self.help_menu.add_command(
            label="Report Issue",
            command=self._report_issue
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

    def _show_about(self):
        try:
            from logger_core.ui.help_dialogs import AboutDialog
            AboutDialog(self.root)
        except Exception as e:
            logger.error("Failed to show About dialog: %s", e)

    def _show_system_info(self):
        try:
            from logger_core.ui.help_dialogs import SystemInfoDialog
            logger_system = getattr(self, 'system', None)
            SystemInfoDialog(self.root, logger_system)
        except Exception as e:
            logger.error("Failed to show System Info dialog: %s", e)

    def _show_help(self):
        try:
            from logger_core.ui.help_dialogs import QuickStartDialog
            QuickStartDialog(self.root)
        except Exception as e:
            logger.error("Failed to show Help dialog: %s", e)

    def _open_logs_directory(self):
        try:
            output_dir = self.get_output_directory()
            logs_dir = output_dir / "logs"

            if not logs_dir.exists():
                logs_dir = output_dir

            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(logs_dir)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(logs_dir)])
            elif sys.platform == 'win32':
                subprocess.Popen(['explorer', str(logs_dir)])

            logger.info("Opened logs directory: %s", logs_dir)
        except Exception as e:
            logger.error("Failed to open logs directory: %s", e)

    def _open_config_file(self):
        try:
            if hasattr(self, 'system') and hasattr(self.system, 'config_file_path'):
                config_path = self.system.config_file_path
            else:
                config_path = Path(__file__).parent.parent / "config.txt"

            if not config_path.exists():
                logger.warning("Config file not found: %s", config_path)
                return

            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(config_path)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(config_path)])
            elif sys.platform == 'win32':
                subprocess.Popen(['notepad.exe', str(config_path)])

            logger.info("Opened config file: %s", config_path)
        except Exception as e:
            logger.error("Failed to open config file: %s", e)

    def _reset_settings(self):
        try:
            if hasattr(self, 'system') and hasattr(self.system, 'config_file_path'):
                config_path = self.system.config_file_path
            else:
                config_path = Path(__file__).parent.parent / "config.txt"

            from logger_core.ui.help_dialogs import ResetSettingsDialog
            ResetSettingsDialog(self.root, config_path)
        except Exception as e:
            logger.error("Failed to reset settings: %s", e)

    def _report_issue(self):
        try:
            url = "https://github.com/JoelCooperPhD/RPi_Logger/issues"
            webbrowser.open(url)
            logger.info("Opened issue tracker: %s", url)
        except Exception as e:
            logger.error("Failed to open issue tracker: %s", e)
