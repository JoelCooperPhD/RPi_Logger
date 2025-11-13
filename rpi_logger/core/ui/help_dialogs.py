
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
                    logo_label = ttk.Label(main_frame, image=logo_photo)
                    logo_label.image = logo_photo
                    logo_label.pack(pady=(0, 20))
            except Exception:
                pass

        title_label = ttk.Label(
            main_frame,
            text="RPi Logger"
        )
        title_label.pack()

        try:
            from logger_core import __version__
            version_text = f"Version {__version__}"
        except ImportError:
            version_text = "Version Unknown"

        version_label = ttk.Label(
            main_frame,
            text=version_text
        )
        version_label.pack(pady=(5, 20))

        info_text = (
            "Professional multi-modal data collection system\n"
            "for automotive research on Raspberry Pi 5.\n\n"
            "Synchronized recording across cameras, microphones,\n"
            "eye tracking, behavioral tasks, and annotations.\n\n"
            "© 2025 RED Scientific\n"
            "All rights reserved."
        )

        info_label = ttk.Label(
            main_frame,
            text=info_text,
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

        self.dialog.geometry("800x650")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame,
            text="Quick Start Guide"
        )
        title_label.pack(pady=(0, 10))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text_widget = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
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

        x = parent.winfo_x() + (parent.winfo_width() // 2) - 400
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 325
        self.dialog.geometry(f"+{x}+{y}")

    def _populate_help(self):
        help_text = """
═══════════════════════════════════════════════════════════════════
                    RPi LOGGER QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW

The RPi Logger is a multi-modal data collection system that coordinates
synchronized recording across cameras, microphones, eye tracking, behavioral
tasks, and annotations. All modules are controlled from a single interface.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. SELECT MODULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   ▸ Navigate to: Modules menu
   ▸ Check the modules you need:
     • Cameras         - Multi-camera video (up to 2x IMX296 @ 1-60 FPS)
     • AudioRecorder   - Multi-microphone audio (8-192 kHz)
     • EyeTracker      - Pupil Labs gaze tracking with scene video
     • NoteTaker       - Timestamped annotations during sessions
     • DRT             - sDRT behavioral task devices

   ▸ Modules launch automatically when checked
   ▸ Wait for green "● Ready" status before recording
   ▸ Uncheck to stop a module


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. START A SESSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   ▸ Click "Start Session" button
   ▸ A new timestamped folder is created: session_YYYYMMDD_HHMMSS/
   ▸ All modules prepare for recording
   ▸ Session timer starts counting

   Important: All modules must show "● Ready" status before recording!


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. RECORD TRIALS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   ▸ Click "Record" to start trial recording
   ▸ All active modules begin capturing data simultaneously
   ▸ Status indicators change to "● RECORDING" (red)
   ▸ Trial timer shows elapsed recording time

   ▸ Click "Stop" to end the current trial
   ▸ Data is saved automatically with trial number
   ▸ Trial counter increments (Trial 1, Trial 2, etc.)

   ▸ Repeat Record → Stop for additional trials
   ▸ All trials are saved to the same session directory


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. END SESSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   ▸ Click "End Session" when finished recording
   ▸ Modules finalize and close recordings
   ▸ Session folder contains all data from all trials
   ▸ Status returns to "Ready" for next session


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. PROCESS RECORDINGS (POST-SESSION)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   After recording, synchronize audio and video:

   $ python -m rpi_logger.tools.muxing_tool
     (select the session folder when prompted)

   Advanced CLI:
     python -m rpi_logger.tools.sync_and_mux data/session_20251024_120000 --all-trials

   These commands create synchronized MP4 files with frame-level accuracy (~30ms).


═══════════════════════════════════════════════════════════════════
                          DATA STRUCTURE
═══════════════════════════════════════════════════════════════════

data/session_20251024_120000/
├── master.log                                    # Main logger log
├── 20251024_120000_SYNC_trial001.json           # Sync metadata
├── 20251024_120000_AV_trial001.mp4              # Muxed audio+video
├── Cameras/
│   ├── session.log
│   ├── 20251024_120000_CAM_trial001_CAM0_1456x1088_30fps.mp4
│   └── 20251024_120000_CAMTIMING_trial001_CAM0.csv
├── AudioRecorder/
│   ├── session.log
│   ├── 20251024_120000_AUDIO_trial001_MIC0_usb-audio.wav
│   └── 20251024_120000_AUDIOTIMING_trial001_MIC0.csv
├── EyeTracker/
│   ├── session.log
│   ├── scene_video_20251024_120000.mp4
│   └── gaze_data_20251024_120000.csv
├── NoteTaker/
│   └── session_notes.csv
└── DRT/
    └── sDRT_dev_ttyACM0_20251024_120000.csv


═══════════════════════════════════════════════════════════════════
                      MODULE STATUS INDICATORS
═══════════════════════════════════════════════════════════════════

○ Stopped          Module not running
○ Starting...      Module launching
○ Initializing...  Hardware initialization in progress
● Ready            Ready to record (green)
● RECORDING        Actively recording data (red)
● Error            Error encountered (red)
● Crashed          Process crashed (red)


═══════════════════════════════════════════════════════════════════
                             TIPS
═══════════════════════════════════════════════════════════════════

✓ Test modules individually before multi-modal sessions
✓ Verify adequate disk space before long sessions (check System Info)
✓ Let cameras/sensors warm up for 30 seconds after starting
✓ Use NoteTaker to annotate events during recording
✓ Process recordings with `python -m rpi_logger.tools.muxing_tool` (or `python -m rpi_logger.tools.sync_and_mux`) immediately after session
✓ Check logs if modules fail: Help > Open Logs Directory
✓ Module windows auto-tile on launch for efficient workspace


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════

Module won't start:
  1. Check green log panel at bottom for error messages
  2. Verify hardware connected: Help > System Information
  3. Kill conflicting processes: $ pkill -f main_camera
  4. Check module log: data/session_*/ModuleName/session.log
  5. Reset if needed: Help > Reset Settings

Recording fails immediately:
  • Verify all modules show "● Ready" before clicking Record
  • Check sufficient disk space (System Information)
  • Review module-specific logs for device errors

Audio/video out of sync:
  • Verify CSV timing files exist in session directory
  • Re-run `python -m rpi_logger.tools.muxing_tool` for the session (or `python -m rpi_logger.tools.sync_and_mux --all-trials`)
  • Check SYNC.json for reasonable offset values

USB devices not detected:
  • Check connections: $ lsusb
  • Verify user in audio group: $ groups
  • Replug device and wait 5 seconds for auto-detection

Need more help?
  • GitHub Issues: Help > Report Issue
  • Documentation: See README.md files in each module
  • Logs: Help > Open Logs Directory


═══════════════════════════════════════════════════════════════════
                        KEYBOARD SHORTCUTS
═══════════════════════════════════════════════════════════════════

Ctrl+Q              Quit application
Ctrl+O              Open data directory
Ctrl+L              Open logs directory
F1                  Open this help dialog
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
