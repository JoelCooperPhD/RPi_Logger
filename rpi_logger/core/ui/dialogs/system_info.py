"""
System information dialog for TheLogger.
"""

import platform
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext

from ..theme import Theme


class SystemInfoDialog:
    """Dialog showing system and module information."""

    def __init__(self, parent, logger_system=None):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("System Information")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("600x500")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame,
            text="System Information"
        )
        title_label.pack(pady=(0, 10))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text_widget = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            state='disabled'
        )
        Theme.configure_scrolled_text(self.text_widget, readonly=True)
        self.text_widget.pack(fill=tk.BOTH, expand=True)

        self._populate_info(logger_system)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))

        close_button = ttk.Button(
            button_frame,
            text="Close",
            command=self.dialog.destroy
        )
        close_button.pack()

        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)

        x = parent.winfo_x() + (parent.winfo_width() // 2) - 300
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 250
        self.dialog.geometry(f"+{x}+{y}")

    def _populate_info(self, logger_system):
        info_lines = []

        info_lines.append("=" * 60)
        info_lines.append("APPLICATION")
        info_lines.append("=" * 60)

        try:
            from rpi_logger.core import __version__
            info_lines.append(f"Version: {__version__}")
        except ImportError:
            info_lines.append("Version: Unknown")

        info_lines.append("")
        info_lines.append("=" * 60)
        info_lines.append("SYSTEM")
        info_lines.append("=" * 60)
        info_lines.append(f"Platform: {platform.system()} {platform.release()}")
        info_lines.append(f"Architecture: {platform.machine()}")
        info_lines.append(f"Python: {sys.version.split()[0]}")
        info_lines.append(f"Python Executable: {sys.executable}")

        info_lines.append("")
        info_lines.append("=" * 60)
        info_lines.append("MODULES")
        info_lines.append("=" * 60)

        if logger_system:
            available_modules = logger_system.get_available_modules()
            if available_modules:
                for module in available_modules:
                    is_running = logger_system.is_module_running(module.name)
                    status = "RUNNING" if is_running else "STOPPED"
                    info_lines.append(f"{module.display_name}: {status}")
            else:
                info_lines.append("No modules discovered")
        else:
            info_lines.append("Logger system not available")

        info_lines.append("")
        info_lines.append("=" * 60)
        info_lines.append("STORAGE")
        info_lines.append("=" * 60)

        if logger_system and hasattr(logger_system, 'session_dir'):
            session_dir = logger_system.session_dir
            info_lines.append(f"Session Directory: {session_dir}")

            try:
                import shutil
                stat = shutil.disk_usage(session_dir)
                total_gb = stat.total / (1024**3)
                used_gb = stat.used / (1024**3)
                free_gb = stat.free / (1024**3)
                percent = (stat.used / stat.total) * 100

                info_lines.append(f"Total Space: {total_gb:.2f} GB")
                info_lines.append(f"Used Space: {used_gb:.2f} GB ({percent:.1f}%)")
                info_lines.append(f"Free Space: {free_gb:.2f} GB")
            except Exception as e:
                info_lines.append(f"Storage info unavailable: {e}")
        else:
            info_lines.append("No active session")

        info_text = "\n".join(info_lines)

        self.text_widget.config(state='normal')
        self.text_widget.insert('1.0', info_text)
        self.text_widget.config(state='disabled')
