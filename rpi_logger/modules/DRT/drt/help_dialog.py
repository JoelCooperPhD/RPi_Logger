"""
DRT Module Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


DRT_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
                    DRT MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Connect your DRT via USB (or XBee dongle for wireless)
   2. Enable the DRT module from the Modules menu
   3. Wait for detection - window title shows connection
      (e.g., "DRT(USB):ACM0" or "DRT(XBee):wDRT_01")
   4. Configure parameters via Device > Configure if needed
   5. Start recording from the main logger to begin trials


USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Real-Time Chart
   Top panel: Stimulus state (ON/OFF)
   Bottom panel: Reaction times
      • Circles = hits
      • X marks = misses
      • 60-second rolling window

Capture Stats Bar
   • Trial: Current trial number
   • RT: Last reaction time (ms) or "Miss"
   • Responses: Button presses this trial
   • Battery: Charge level (wDRT only)

Device Menu
   • Stimulus: ON/OFF - Manual trigger for testing
   • Configure... - Timing parameter settings

Note: Device menu is disabled during recording.


CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Access via Device > Configure...

   Upper ISI (ms)    Maximum inter-stimulus interval
   Lower ISI (ms)    Minimum inter-stimulus interval
   Stim Duration     Response window before timeout
   Intensity (%)     LED brightness / vibration strength

Buttons:
   • Upload Custom - Send your values to device
   • Upload ISO - Apply ISO 17488 defaults:
     Lower ISI: 3000ms, Upper ISI: 5000ms, Duration: 1000ms


DATA OUTPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Files saved to: {session_dir}/DRT/

sDRT columns (7):
   Device ID, Label, Unix time, Milliseconds Since Record,
   Trial Number, Responses, Reaction Time

wDRT columns (9):
   Same as sDRT plus: Battery Percent, Device time in UTC

Example row:
   sDRT_ttyACM0,baseline,1702000000,5234,1,1,312

Reaction time of -1 indicates a miss (no response).


DEVICE TYPES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

sDRT
   USB at 9600 baud, wired response button

wDRT USB
   USB at 921600 baud, battery monitoring, RTC sync

wDRT Wireless
   XBee mesh network, fully wireless, battery-powered


TROUBLESHOOTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Device not detected:
   • Check USB connection and device power
   • Run 'lsusb' to verify device is visible
   • Add user to dialout group if permission denied:
     sudo usermod -a -G dialout $USER
     (log out and back in after)

No data recording:
   • Ensure recording is started from main logger
   • Check session directory is writable

Wireless issues (wDRT):
   • Verify XBee dongle is connected
   • Check battery level
   • Move closer to reduce interference


"""


class DRTHelpDialog:
    """Dialog showing DRT quick start guide."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("DRT Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("700x600")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame,
            text="DRT Quick Start Guide"
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
        self.text_widget.insert('1.0', DRT_HELP_TEXT)
        self.text_widget.config(state='disabled')
