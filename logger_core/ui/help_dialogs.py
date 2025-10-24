
import platform
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None


class AboutDialog:

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("About")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.dialog.geometry("500x350")
        self.dialog.resizable(False, False)

        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        if Image and ImageTk:
            try:
                logo_path = Path(__file__).parent / "logo_100.png"
                if logo_path.exists():
                    logo_image = Image.open(logo_path)
                    logo_photo = ImageTk.PhotoImage(logo_image)
                    logo_label = tk.Label(main_frame, image=logo_photo)
                    logo_label.image = logo_photo
                    logo_label.pack(pady=(0, 20))
            except Exception:
                pass

        title_label = tk.Label(
            main_frame,
            text="RPi Logger",
            font=("Helvetica", 20, "bold")
        )
        title_label.pack()

        try:
            from logger_core import __version__
            version_text = f"Version {__version__}"
        except ImportError:
            version_text = "Version Unknown"

        version_label = tk.Label(
            main_frame,
            text=version_text,
            font=("Helvetica", 10)
        )
        version_label.pack(pady=(5, 20))

        info_text = (
            "Multi-modal data logging system for\n"
            "human factors research and vehicle testing.\n\n"
            "© 2025 RED Scientific\n"
            "All rights reserved."
        )

        info_label = tk.Label(
            main_frame,
            text=info_text,
            font=("Helvetica", 10),
            justify=tk.CENTER
        )
        info_label.pack(pady=10)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(20, 0))

        close_button = ttk.Button(
            button_frame,
            text="Close",
            command=self.dialog.destroy
        )
        close_button.pack()

        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)

        x = parent.winfo_x() + (parent.winfo_width() // 2) - 250
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 175
        self.dialog.geometry(f"+{x}+{y}")


class SystemInfoDialog:

    def __init__(self, parent, logger_system=None):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("System Information")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.dialog.geometry("600x500")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = tk.Label(
            main_frame,
            text="System Information",
            font=("Helvetica", 14, "bold")
        )
        title_label.pack(pady=(0, 10))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text_widget = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            font=("Courier", 9),
            state='disabled'
        )
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
            from logger_core import __version__
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


class QuickStartDialog:

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.dialog.geometry("700x550")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = tk.Label(
            main_frame,
            text="Quick Start Guide",
            font=("Helvetica", 14, "bold")
        )
        title_label.pack(pady=(0, 10))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text_widget = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            font=("Helvetica", 10),
            state='disabled'
        )
        self.text_widget.pack(fill=tk.BOTH, expand=True)

        self._populate_help()

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))

        close_button = ttk.Button(
            button_frame,
            text="Close",
            command=self.dialog.destroy
        )
        close_button.pack()

        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)

        x = parent.winfo_x() + (parent.winfo_width() // 2) - 350
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 275
        self.dialog.geometry(f"+{x}+{y}")

    def _populate_help(self):
        help_text = """
GETTING STARTED WITH RPI LOGGER

1. SELECT MODULES
   • Open the Modules menu
   • Check the modules you want to use (Cameras, Audio, Eye Tracker, etc.)
   • Each module will start automatically when checked

2. START A SESSION
   • Click the "Start" button in the Session control panel
   • Select a directory where session data will be saved
   • A new session folder will be created with a timestamp

3. CONFIGURE TRIAL LABEL (Optional)
   • Enter a label in the "Trial Label" field
   • This label will be associated with the next trial recording
   • Use descriptive names like "baseline", "test1", etc.

4. RECORD TRIALS
   • Click "Record" in the Trial control panel to start recording
   • All active modules will begin capturing data
   • Click "Pause" to stop the current trial
   • Trial counter will increment automatically

5. MONITOR STATUS
   • Current Time: Real-time clock
   • Session Time: Duration of current session
   • Trial Time: Duration of current trial
   • Trial Count: Number of completed trials
   • Status: Current system state
   • Path: Location of session data

6. STOP SESSION
   • Click "Stop" in the Session control panel
   • All trials will be finalized
   • Session data remains in the selected directory

7. SHUTDOWN
   • Click "Shutdown Logger" to exit the application
   • Running modules will be saved and auto-started next time
   • Window position and settings are saved automatically

DATA ORGANIZATION

Session data is organized as follows:
  session_YYYYMMDD_HHMMSS/
  ├── logs/              (system logs)
  ├── Camera/            (camera recordings)
  ├── Audio/             (audio recordings)
  ├── EyeTracker/        (gaze data)
  └── Notes/             (text notes)

Each module creates its own subdirectory with recordings and metadata.

TIPS

• Use the File menu to quickly open the output directory
• Module status indicators show [Ready], [RECORDING], [Error], etc.
• The logger panel at the bottom shows real-time log messages
• Configuration files can be edited to customize behavior
• Each module can be run standalone for testing

TROUBLESHOOTING

If a module fails to start:
  1. Check the logger panel for error messages
  2. Open Help > System Information to check hardware status
  3. View logs in Help > Open Logs Directory
  4. Try resetting settings via Help > Reset Settings
  5. Report issues via Help > Report Issue

For more information, visit the project repository or contact support.
"""

        self.text_widget.config(state='normal')
        self.text_widget.insert('1.0', help_text)
        self.text_widget.config(state='disabled')


class ResetSettingsDialog:

    def __init__(self, parent, config_path: Path, on_reset_callback=None):
        self.config_path = config_path
        self.on_reset_callback = on_reset_callback

        response = messagebox.askyesno(
            "Reset Settings",
            "This will reset all configuration settings to their default values.\n\n"
            "A backup of your current config will be saved.\n\n"
            "Are you sure you want to continue?",
            parent=parent
        )

        if response:
            self._reset_config()

    def _reset_config(self):
        try:
            if self.config_path.exists():
                backup_path = self.config_path.with_suffix('.txt.backup')
                import shutil
                shutil.copy2(self.config_path, backup_path)

            default_config = self._get_default_config()

            with open(self.config_path, 'w') as f:
                f.write(default_config)

            messagebox.showinfo(
                "Reset Complete",
                f"Settings have been reset to defaults.\n\n"
                f"Backup saved to: {self.config_path.with_suffix('.txt.backup')}\n\n"
                f"Please restart the application for changes to take effect."
            )

            if self.on_reset_callback:
                self.on_reset_callback()

        except Exception as e:
            messagebox.showerror(
                "Reset Failed",
                f"Failed to reset settings: {e}"
            )

    def _get_default_config(self) -> str:
        return """################################################################################
# MASTER LOGGER CONFIGURATION
################################################################################

data_dir = data
session_prefix = session
log_level = info
console_output = false
ui_update_rate_hz = 10
window_x = 0
window_y = 0
window_width = 800
window_height = 600
"""
