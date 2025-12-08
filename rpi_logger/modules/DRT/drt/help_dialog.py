"""
DRT Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


DRT_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
                    DRT MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW

The DRT (Detection Response Task) module measures cognitive workload
by recording reaction times to visual stimuli. Participants respond
to a red LED stimulus by pressing a button as quickly as possible.
Degraded reaction times indicate increased cognitive load.

The module supports two device types:
  • sDRT (Simple DRT)    - USB-connected tactile response device
  • wDRT (Wireless DRT)  - XBee wireless response device

Devices are auto-detected when plugged in via USB.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Connect your DRT device via USB (or XBee dongle for wDRT)
   2. Enable the DRT module from the Modules menu
   3. Wait for device detection (status shows device port)
   4. Start a session to begin recording reaction times


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Real-time Chart
   The main display shows:
   • Upper plot - Stimulus state (ON/OFF) over time
   • Lower plot - Reaction time bar chart for each trial

   During recording, the chart scrolls to show a 60-second window
   of stimulus activity and reaction times.

Results Panel (Capture Stats)
   • Trial    - Current trial number
   • RT       - Last reaction time in milliseconds (or "Miss")
   • Responses - Total button press count
   • Battery  - Battery level (wDRT only)

Device Menu
   • Stimulus: ON  - Manually turn on the LED stimulus
   • Stimulus: OFF - Manually turn off the LED stimulus
   • Configure...  - Open device configuration dialog


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. RECORDING SESSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Starting a Session
   When you start a recording session:
   • Device enters experiment mode
   • Chart clears and begins fresh
   • Trial counter resets
   • Stimulus cycle begins automatically

During Recording
   The DRT device automatically:
   • Presents stimuli at random intervals (ISI range)
   • Records reaction time for each stimulus
   • Marks misses when no response before timeout

   Each trial captures:
   • Stimulus onset time
   • Response time (or miss indicator)
   • Reaction time (response - onset)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3.5. OUTPUT FILES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File Naming Convention
   {timestamp}_DRT_trial{NNN}_{device_id}.csv

   Example: 20251208_143022_DRT_trial001_sDRT_ttyACM0.csv

Location
   {session_dir}/DRT/


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3.6. CSV FIELD REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

sDRT CSV Columns (7 fields):
   Device ID             - Device identifier (e.g., "sDRT")
   Label                 - Device port/label (e.g., "ttyACM0")
   Unix time in UTC      - Stimulus onset timestamp (Unix seconds)
   Milliseconds Since Record - Time since recording started (ms)
   Trial Number          - Sequential trial count (1-based)
   Responses             - Button press count for this trial
   Reaction Time         - Response latency in ms (-1 = miss)

wDRT CSV Columns (9 fields):
   [Same first 7 columns as sDRT, plus:]
   Total                 - Cumulative response count
   Lens                  - VOG lens state (if synced, else empty)
   Battery Percent       - Device battery level (0-100%)

Example Rows:
   sDRT:
   sDRT,ttyACM0,1733649120.123,5000,1,1,342

   wDRT:
   wDRT,xbee_001,1733649120.456,5500,2,1,287,15,,85


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3.7. TIMING & SYNCHRONIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Reaction Time Measurement
   Reaction Time = Device End Time - Stimulus Onset Time

   The DRT device firmware measures reaction time internally
   with typical accuracy of ±1-5 ms.

Timestamp Precision
   Unix time in UTC      - Microsecond precision (6 decimals)
   Milliseconds Since Record - Integer milliseconds
   Reaction Time         - Integer milliseconds

Miss Detection
   A reaction time of -1 indicates a "miss":
   • Participant did not respond before stimulus timeout
   • Stimulus duration elapsed without button press

Cross-Module Synchronization
   Use "Unix time in UTC" to correlate DRT events with:
   • Video frames (via camera timing CSV)
   • Audio samples (via audio timing CSV)
   • Eye tracking data (via gaze CSV)
   • VOG lens states (wDRT Lens column when synced)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Click Device > Configure to access device settings.

Timing Parameters:
   • Lower ISI    - Minimum inter-stimulus interval (ms)
   • Upper ISI    - Maximum inter-stimulus interval (ms)
   • Stim Duration - How long stimulus stays on (ms)
   • Intensity    - LED brightness (0-100%)

ISO 17488 Standard Values:
   Click "ISO Defaults" to apply standard parameters:
   • Lower ISI: 3000 ms
   • Upper ISI: 5000 ms
   • Stimulus Duration: 1000 ms
   • Intensity: 100%

Get Config
   Reads current parameters from the device.

Upload
   Sends new parameters to the device.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. UNDERSTANDING RESULTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Reaction Times
   • Normal range: 200-500 ms (unloaded baseline)
   • Elevated RT (>500 ms) indicates increased cognitive load
   • Very fast RT (<150 ms) may indicate anticipation

Misses
   A "Miss" occurs when the participant fails to respond before
   the stimulus turns off. Misses indicate:
   • High cognitive workload
   • Inattention to the DRT task
   • Possible equipment issues (check device)

Hit Rate
   The percentage of stimuli receiving valid responses.
   Lower hit rates indicate higher cognitive demand.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. DEVICE TYPES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

sDRT (Simple DRT)
   USB-connected device with:
   • Tactile response button
   • Red LED stimulus
   • Direct USB serial communication

   Connection: USB cable to computer
   Port appears as: /dev/ttyACM0 (Linux) or COM port (Windows)

wDRT (Wireless DRT)
   XBee-based wireless device with:
   • Same response mechanism as sDRT
   • Battery powered for mobility
   • XBee radio for wireless data

   Connection: XBee USB dongle to computer
   Supports multiple wDRT devices on same network


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════

Device not detected:
   1. Check USB connection
   2. Verify device is powered on (wDRT: check battery)
   3. Run 'lsusb' or check /dev/ttyACM* for device
   4. Check the log panel for connection errors
   5. Try unplugging and reconnecting

No reaction times recorded:
   1. Ensure recording session is active
   2. Verify stimulus LED is blinking
   3. Check that button presses register (Responses count)
   4. Review device configuration (ISI settings)

All responses showing as "Miss":
   1. Check stimulus duration is adequate (>500 ms)
   2. Verify participant understands the task
   3. Test button responsiveness manually
   4. Check for loose connections

Configure button doesn't work:
   1. Wait for device to fully connect
   2. Ensure not currently recording
   3. Check that runtime is bound (wait a moment after launch)

wDRT not connecting:
   1. Verify XBee dongle is connected
   2. Check wDRT battery level
   3. Ensure devices are on same XBee network
   4. Move devices closer together


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
