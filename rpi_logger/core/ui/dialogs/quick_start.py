"""
Quick start guide dialog for Logger.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from ..theme import Theme


QUICK_START_TEXT = """
═══════════════════════════════════════════════════════════════════
                       LOGGER QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW

Logger is a multi-modal data collection system that coordinates
synchronized recording across cameras, microphones, eye tracking, behavioral
tasks, and annotations. All modules are controlled from a single interface.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. SELECT MODULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   ▸ Navigate to: Modules menu
   ▸ Check the modules you need:
     • Cameras         - Multi-camera video (up to 2x IMX296 @ 1-60 FPS)
     • AudioRecorder   - Multi-microphone audio (8-192 kHz)
     • EyeTracker-Neon - Pupil Labs Neon gaze tracking with scene video
     • Notes           - Stub-based annotations during sessions
     • DRT             - DRT behavioral task devices

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
├── EyeTracker-Neon/
│   ├── session.log
│   ├── scene_video_20251024_120000.mp4
│   └── gaze_data_20251024_120000.csv
├── Notes/
│   └── session_notes.csv
└── DRT/
    └── DRT_dev_ttyACM0_20251024_120000.csv


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
✓ Use the Notes module to annotate events during recording
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


"""


class QuickStartDialog:
    """Dialog showing the quick start guide."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

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
        Theme.configure_scrolled_text(self.text_widget, readonly=True)
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
        self.text_widget.config(state='normal')
        self.text_widget.insert('1.0', QUICK_START_TEXT)
        self.text_widget.config(state='disabled')
