"""
VOG Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


VOG_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
                    VOG MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW

The VOG (Visual Occlusion Glasses) module controls electronic shutter
glasses for vision research experiments. The glasses can rapidly switch
between clear (transparent) and opaque states, enabling precise control
of visual stimulus presentation.

Devices are auto-detected when plugged in via USB.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Connect your VOG device via USB
   2. Enable the VOG module from the Modules menu
   3. Wait for the device tab to appear (indicates successful detection)
   4. Use the lens controls or start a recording session


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Device Tabs
   Each connected device gets its own tab showing:
   • Real-time Chart - Stimulus state and shutter timing (60s window)
   • Lens Controls   - Buttons to manually open/close lenses
   • Results Panel   - Trial number and timing data (TSOT/TSCT)
   • Configure       - Opens device settings dialog

Lens Controls
   • Clear/Open   - Opens the lens (transparent)
   • Opaque/Close - Closes the lens (blocks vision)

   Wireless devices have additional buttons for independent
   left/right lens control.

Results Display
   After each trial:
   • Trial Number - Current trial count
   • TSOT - Total Shutter Open Time (milliseconds)
   • TSCT - Total Shutter Close Time (milliseconds)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. RECORDING SESSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Starting a Session
   When you start a recording session:
   • Device enters experiment mode
   • Chart clears and begins fresh
   • Trial counter resets to 1

During Recording
   Each trial captures:
   • Timing data for all lens state changes
   • Accumulated open/close durations
   • Timestamps synchronized to system time


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3.5. OUTPUT FILES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File Naming Convention
   {timestamp}_VOG_{port}.csv

   Example: 20251208_143022_VOG_ttyACM0.csv
   (Trial number is stored in the CSV data column.)

Location
   {session_dir}/VOG/


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3.6. CSV FIELD REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

sVOG CSV Columns (7 fields):
   Device ID             - Device identifier (e.g., "sVOG")
   Label                 - Device port/label (e.g., "ttyACM0")
   Unix time in UTC      - Event timestamp (Unix seconds, 6 decimals)
   Milliseconds Since Record - Time since recording started (ms)
   Trial Number          - Sequential trial count (1-based)
   TSOT                  - Total Shutter Open Time (milliseconds)
   TSCT                  - Total Shutter Close Time (milliseconds)

wVOG CSV Columns (10 fields):
   [Same first 7 columns as sVOG, plus:]
   Lens                  - Lens state (Open/Closed/Left/Right)
   Battery Percent       - Device battery level (0-100%)
   DRT Reaction Time     - Reaction time if DRT synced (ms, or empty)

Example Rows:
   sVOG:
   sVOG,ttyACM0,1733649120.123456,5000,1,1500,3500

   wVOG:
   wVOG,xbee_002,1733649120.456789,5500,2,3000,2500,Open,85,


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3.7. TIMING & SYNCHRONIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Timing Precision
   TSOT/TSCT:            Millisecond precision (device firmware)
   Unix time in UTC:     Microsecond precision (6 decimals)
   Lens state changes:   Device-measured (<50ms close, <15ms open)

Lens State Timing
   Lens transitions are timestamped by the device firmware.
   Each row represents a lens state change event.
   TSOT and TSCT accumulate across the trial.

Cross-Module Synchronization
   Use "Unix time in UTC" to correlate VOG events with:
   • Video frames (via camera capture_time_unix)
   • Audio samples (via audio record_time_unix)
   • DRT trials (via DRT record_time_unix)
   • Eye tracking data (via record_time_unix)

DRT Integration (wVOG only)
   When wVOG is synced with wDRT on the same XBee network:
   • DRT Reaction Time column shows reaction times
   • Lens column in DRT CSV shows VOG lens state
   • Enables combined visual occlusion + reaction time studies


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Click "Configure Unit" on any device tab to access settings.

Common Settings:
   • Open/Close Time - Lens timing duration (ms)
   • Debounce        - Button debounce time (ms)
   • Opacity         - Lens transparency levels (0-100%)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. EXPERIMENT TYPES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Cycle
   Standard visual occlusion testing following NHTSA Visual Manual
   Distraction Guidelines and ISO 16673.

   How it works: The lenses automatically alternate between clear
   and opaque at fixed intervals (e.g., 1.5 seconds each).
   Participants perform a task while only able to see during the
   clear periods. The system records total shutter open time (TSOT)
   and total task time.

   Use case: Measuring the visual demand of in-vehicle interfaces
   and other tasks requiring intermittent visual attention.

Peek
   For testing interfaces where the primary modality is non-visual
   (e.g., auditory or haptic) but occasional visual confirmation
   may be needed.

   How it works: Lenses start opaque. Participants press a button
   to request a "peek" - the lenses clear for a set duration
   (default 1.5 seconds) then return to opaque. A lockout period
   prevents consecutive peeks.

   Data collected: Number of peeks and cumulative peek time,
   providing a measure of visual attention demand for interfaces
   designed for eyes-free operation.

   Use case: Evaluating voice-controlled or auditory display
   systems where visual glances should be minimized.

eBlindfold
   For measuring visual search time.

   How it works: Trial begins with lenses clear. The participant
   searches for a specified target. Upon locating the target,
   they press the button - the lenses immediately go opaque and
   the trial ends. Total shutter open time equals search time.

   Use case: Measuring visual search performance, comparing
   display layouts, or evaluating icon/element discoverability.

Direct
   Simple manual control mode for integrating with external
   equipment or custom experiment setups.

   How it works: The lenses directly mirror the button state -
   press and hold to clear, release to go opaque (or vice versa).
   No timing data is recorded by the glasses themselves.

   Use case: When you need to control the glasses from other
   laboratory equipment, or for demonstrations and testing.


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════

Device not detected:
   1. Check USB connection
   2. Verify device is powered on
   3. Run 'lsusb' to confirm device is visible
   4. Check the log panel for connection errors

No data after trial:
   1. Ensure recording was started before the trial
   2. Check that the session directory exists and is writable
   3. Review module logs for errors

Lens not responding:
   1. Try Configure > Refresh to reload device state
   2. Check battery level (wVOG)
   3. Reconnect the USB cable
   4. Restart the module


"""


class VOGHelpDialog:
    """Dialog showing VOG quick start guide."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("VOG Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("700x600")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame,
            text="VOG Quick Start Guide"
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
        self.text_widget.insert('1.0', VOG_HELP_TEXT)
        self.text_widget.config(state='disabled')
