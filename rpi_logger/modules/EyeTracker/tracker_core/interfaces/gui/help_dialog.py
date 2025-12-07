"""
Eye Tracker Module Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


EYETRACKER_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
               EYE TRACKER MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW

The Eye Tracker module captures gaze data and scene video from
Pupil Labs eye tracking glasses. It records where participants
are looking in real-time, synchronized with other data streams.

The tracker connects via USB or network.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Power on your Pupil Labs glasses
   2. Connect via USB cable
   3. Enable the Eye Tracker module from the Modules menu
   4. Wait for device connection (status shows "Connected")
   5. Calibrate if needed using Pupil Capture
   6. Start a session to begin recording


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Preview Display
   Shows the scene camera feed with gaze overlay:
   • Red circle indicates current gaze position
   • Scene video shows participant's view

Device Status Panel
   • Device: Connected device name
   • Status: Connection state (Connected/Disconnected)
   • Recording: Current recording state (Active/Idle)

Controls
   • Reconnect: Attempt to reconnect to device
   • Configure: Open device settings dialog


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. RECORDING SESSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Starting a Session
   When you start a recording session:
   • Gaze data recording begins
   • Scene video capture starts
   • Status shows "Active"

During Recording
   Each trial captures:
   • Gaze coordinates (x, y) normalized to scene
   • Pupil diameter for each eye
   • Confidence values for gaze estimation
   • Scene video with embedded timestamps

Data Output
   Gaze data is saved as CSV:
   {session_dir}/EyeTracker/gaze_data_{timestamp}.csv

   Scene video is saved as:
   {session_dir}/EyeTracker/scene_video_{timestamp}.mp4


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Click "Configure" to access device settings.

Available Settings:
   • Scene Camera Resolution
   • Gaze Sample Rate
   • Pupil Detection Threshold
   • Network Connection Settings


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. DATA INTERPRETATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Gaze Position (norm_x, norm_y)
   Normalized coordinates (0-1) in scene camera view.
   (0,0) is top-left, (1,1) is bottom-right.

Confidence
   Quality of gaze estimate (0-1).
   Higher values indicate more reliable tracking.

Pupil Diameter
   Measured in millimeters.
   Changes reflect cognitive load and lighting.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. CALIBRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For accurate gaze data, calibrate before each session:

   1. Open Pupil Capture on the host computer
   2. Select appropriate calibration method
   3. Follow on-screen instructions
   4. Verify accuracy with validation targets

Recalibrate if:
   • Glasses are repositioned on face
   • Significant time has passed
   • Gaze accuracy appears poor


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════

Device not detected:
   1. Check USB cable connection
   2. Verify Pupil Capture is running
   3. Check network settings if using WiFi
   4. Click "Reconnect" button

No gaze data appearing:
   1. Ensure calibration was completed
   2. Check pupil detection in Pupil Capture
   3. Verify adequate lighting conditions
   4. Clean eye camera lenses

Scene video not recording:
   1. Check scene camera connection
   2. Verify camera is not in use by other app
   3. Check available disk space
   4. Review module logs for errors

Poor gaze accuracy:
   1. Recalibrate the tracker
   2. Ensure glasses fit snugly
   3. Check for reflections on lenses
   4. Verify pupil detection is stable


"""


class EyeTrackerHelpDialog:
    """Dialog showing Eye Tracker quick start guide."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Eye Tracker Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("700x600")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame,
            text="Eye Tracker Quick Start Guide"
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

        x = parent.winfo_x() + (parent.winfo_width() // 2) - 350
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 300
        self.dialog.geometry(f"+{x}+{y}")

    def _populate_help(self):
        self.text_widget.config(state='normal')
        self.text_widget.insert('1.0', EYETRACKER_HELP_TEXT)
        self.text_widget.config(state='disabled')
