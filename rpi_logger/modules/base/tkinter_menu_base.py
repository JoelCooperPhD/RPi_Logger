
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from typing import Callable, Optional

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


class TkinterMenuBase:

    def create_menu_bar(self, include_sources: bool = True):
        if not hasattr(self, 'root'):
            raise AttributeError("TkinterMenuBase requires 'self.root' attribute")

        logger_visible_default = self.get_logger_visible_from_config()
        self.logger_visible_var = tk.BooleanVar(value=logger_visible_default)
        self._menus_available = not getattr(self, "_embedded_mode", False)

        if not self._menus_available:
            logger.debug("Skipping legacy menu bar creation for embedded GUI")
            self.file_menu = None
            self.sources_menu = None
            self.view_menu = None
            self.help_menu = None
            self._apply_logger_visibility()
            return

        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

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
            label="Open Log File",
            command=self._on_open_log_file
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
            label="Show System Log",
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


    def add_source_toggle(self, label: str, variable: tk.BooleanVar,
                         command: Callable) -> int:
        if not getattr(self, "_menus_available", True) or getattr(self, "sources_menu", None) is None:
            logger.debug("Sources menu unavailable; cannot add toggle '%s'", label)
            return -1
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
        if not getattr(self, "_menus_available", True) or getattr(self, "view_menu", None) is None:
            logger.debug("View menu unavailable; cannot add option '%s'", label)
            return -1
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

        grid_options = widget.grid_info()
        if grid_options:
            grid_options = grid_options.copy()
            grid_options.pop('in', None)
        else:
            grid_options = {}

        def toggle():
            visible = var.get()
            if visible:
                if grid_options:
                    regrid_kwargs = {}
                    for key, value in grid_options.items():
                        if isinstance(value, str) and value.isdigit():
                            try:
                                regrid_kwargs[key] = int(value)
                                continue
                            except ValueError:
                                pass
                        regrid_kwargs[key] = value
                    widget.grid()
                    widget.grid_configure(**regrid_kwargs)
                else:
                    widget.grid()
            else:
                widget.grid_remove()
            self._save_view_state(config_key, visible)

            try:
                widget.winfo_toplevel().update_idletasks()
            except Exception:
                pass

        self.add_view_option(label, var, toggle)

        if not initial_state:
            widget.grid_remove()

        return var

    def enable_sources_menu(self, enabled: bool):
        if not getattr(self, "_menus_available", True) or getattr(self, "sources_menu", None) is None:
            return
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

    def get_log_file(self) -> Path:
        if hasattr(self, 'args') and hasattr(self.args, 'log_file'):
            return Path(self.args.log_file)
        raise NotImplementedError(
            "Log file not available. Module must call setup_module_logging() and store log_file in args."
        )

    def _load_view_state(self, config_key: str, default: bool) -> bool:
        if hasattr(self, 'system') and hasattr(self.system, 'config'):
            config = self.system.config
            if isinstance(config, dict):
                value = config.get(config_key, default)
                if isinstance(value, str):
                    value_lower = value.lower()
                    if value_lower in ('true', 'yes', 'on', '1'):
                        return True
                    if value_lower in ('false', 'no', 'off', '0'):
                        return False
                return value if isinstance(value, bool) else default
            else:
                value = getattr(config, config_key, default)
                if isinstance(value, str):
                    value_lower = value.lower()
                    if value_lower in ('true', 'yes', 'on', '1'):
                        return True
                    if value_lower in ('false', 'no', 'off', '0'):
                        return False
                return value if isinstance(value, bool) else default
        return default

    def _save_view_state(self, config_key: str, visible: bool):
        try:
            if hasattr(self, 'system') and hasattr(self.system, 'config'):
                config = self.system.config
                if isinstance(config, dict):
                    config[config_key] = visible
                else:
                    setattr(config, config_key, visible)

                # Prefer using preferences API if available (routes through ConfigManager)
                if hasattr(self.system, 'preferences'):
                    self.system.preferences.write_sync({config_key: visible})
                    logger.debug("Saved view state %s=%s via preferences", config_key, visible)
                elif hasattr(self.system, 'config_file_path'):
                    from rpi_logger.modules.base import ConfigLoader
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
                logger.info("System log shown")
            else:
                self.log_frame.grid_remove()
                logger.info("System log hidden")

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

    def _on_open_log_file(self):
        try:
            log_file = self.get_log_file()

            if not log_file.exists():
                logger.warning("Log file does not exist: %s", log_file)
                return

            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(log_file)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(log_file)])
            elif sys.platform == 'win32':
                subprocess.Popen(['notepad.exe', str(log_file)])

            logger.info("Opened log file: %s", log_file)
        except Exception as e:
            logger.error("Failed to open log file: %s", e)

    def _on_quit(self):
        handler = None

        system = getattr(self, 'system', None)
        if system is not None:
            handler = getattr(getattr(system, 'mode_instance', None), 'on_closing', None)

        if handler is None:
            handler = getattr(self, 'on_closing', None)
        if handler is None:
            handler = getattr(self, '_on_closing', None)

        if handler is not None:
            handler()
            return

        logger.warning("No close handler found, destroying window directly")
        if hasattr(self, 'root'):
            self.root.destroy()

    def _show_about(self):
        try:
            from rpi_logger.core.ui.dialogs.about import AboutDialog
            AboutDialog(self.root)
        except Exception as e:
            logger.error("Failed to show About dialog: %s", e)

    def _show_system_info(self):
        try:
            from rpi_logger.core.ui.dialogs.system_info import SystemInfoDialog
            logger_system = getattr(self, 'system', None)
            SystemInfoDialog(self.root, logger_system)
        except Exception as e:
            logger.error("Failed to show System Info dialog: %s", e)

    def _show_help(self):
        try:
            from rpi_logger.core.ui.dialogs.quick_start import QuickStartDialog
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

            from rpi_logger.core.ui.dialogs.reset_settings import ResetSettingsDialog
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
