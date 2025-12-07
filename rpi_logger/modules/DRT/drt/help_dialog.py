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

OVERVIEW

The DRT (Detection Response Task) module measures secondary task
response times during driving or other primary tasks. It presents
a visual or tactile stimulus at random intervals and records how
quickly participants respond.

Devices are auto-detected when connected via USB.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Connect your DRT device via USB
   2. Enable the DRT module from the Modules menu
   3. Wait for device detection (controls appear when ready)
   4. Configure timing parameters if needed
   5. Start a session to begin data collection


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Real-Time Chart
   Displays stimulus events and reaction times:
   • Vertical lines mark stimulus presentations
   • Dots indicate response times
   • 60-second scrolling window

Stimulus Controls
   • ON: Manually trigger stimulus (for testing)
   • OFF: Cancel active stimulus

Results Display
   • Trial Number: Current trial count
   • Reaction Time: Last response time (ms) or "Miss"
   • Response Count: Total button presses

Configure Unit
   Opens device settings dialog for timing parameters.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. RECORDING SESSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Starting a Session
   When you start a recording session:
   • DRT enters experiment mode
   • Chart clears and begins fresh
   • Trial counter resets to 1

During Recording
   Each trial captures:
   • Stimulus onset time
   • Response time (or miss indicator)
   • Inter-stimulus interval
   • All timing synchronized to system clock

Data Output
   Trial data is saved as CSV:
   {session_dir}/DRT/{timestamp}_DRT_trial{N}_{port}.csv


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Click "Configure Unit" to access device settings.

ISO 17488 Parameters:
   • Lower ISI: Minimum inter-stimulus interval (ms)
   • Upper ISI: Maximum inter-stimulus interval (ms)
   • Stimulus Duration: How long stimulus stays on (ms)
   • Intensity: LED/vibration strength (0-100%)

Use "ISO Preset" button to apply standard values:
   • Lower ISI: 3000 ms
   • Upper ISI: 5000 ms
   • Stimulus Duration: 1000 ms (until response)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. DEVICE TYPES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

sDRT (Stationary DRT)
   • USB-connected device
   • Visual stimulus (LED)
   • Wired response button
   • Ideal for laboratory studies

wDRT (Wireless DRT)
   • Wireless connection via XBee
   • Visual or tactile stimulus
   • Portable response unit
   • Battery-powered for in-vehicle use


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. UNDERSTANDING DRT DATA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Reaction Time
   Time from stimulus onset to button press (ms).
   Typical range: 200-800 ms

Miss
   No response within the allowed window.
   Indicates high cognitive load or inattention.

Hit Rate
   Percentage of stimuli with valid responses.
   Lower hit rates suggest higher task demands.


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════

Device not detected:
   1. Check USB connection
   2. Verify device is powered on
   3. Run 'lsusb' to confirm device visible
   4. Check serial port permissions (/dev/ttyACM*)

No stimulus on button press:
   1. Verify device is not in experiment mode
   2. Check that recording is not active
   3. Use the manual ON/OFF buttons to test
   4. Review device configuration settings

Data not recording:
   1. Ensure session is started before recording
   2. Check session directory exists and is writable
   3. Review module logs for errors

Wireless device connection issues:
   1. Check XBee dongle is connected
   2. Verify device batteries are charged
   3. Ensure device is paired with dongle
   4. Check for RF interference


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
