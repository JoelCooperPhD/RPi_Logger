"""
Audio Module Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


AUDIO_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
                   AUDIO MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW

The Audio module records synchronized audio from USB microphones
during experiment sessions. It supports multiple audio input
devices and provides real-time level monitoring.

Devices are discovered by the main logger and assigned to this module.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Connect your USB microphone(s)
   2. Enable the Audio module from the Modules menu
   3. Wait for device assignment (meters appear when ready)
   4. Start a session to begin recording


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Device Selection
   Audio devices are assigned by the main logger.
   Assigned devices show level meters in the control panel.

Level Meters
   Real-time audio level visualization:
   • Green bars indicate normal audio levels
   • Yellow indicates moderate levels
   • Red indicates clipping or very high levels


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. RECORDING SESSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Starting a Session
   When you start a recording session:
   • Audio capture begins on all selected devices
   • Level meters remain active for monitoring
   • Recording indicator shows "RECORDING" status

During Recording
   Each trial captures:
   • WAV audio files for each microphone
   • Timing CSV with sample-accurate timestamps
   • Metadata for synchronization

Data Output
   Audio data is saved as WAV files:
   {session_dir}/AudioRecorder/{timestamp}_AUDIO_trial{N}_{device}.wav

   Timing data for synchronization:
   {session_dir}/AudioRecorder/{timestamp}_AUDIOTIMING_trial{N}_{device}.csv


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Sample Rate
   Configurable from 8 kHz to 192 kHz depending on device.
   Higher rates provide better quality but larger files.

Channels
   Mono or stereo depending on microphone capabilities.


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════

Device not detected:
   1. Check USB connection
   2. Verify device is powered on
   3. Run 'arecord -l' to list available devices
   4. Check that user is in the 'audio' group

No audio in recording:
   1. Check input levels in the meter display
   2. Verify microphone is not muted
   3. Test with 'arecord -d 5 test.wav' in terminal
   4. Check device permissions

Level meter shows no activity:
   1. Speak into the microphone
   2. Check physical mute switches
   3. Verify correct device is selected
   4. Restart the module


"""


class AudioHelpDialog:
    """Dialog showing Audio quick start guide."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Audio Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("700x600")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame,
            text="Audio Quick Start Guide"
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
        self.text_widget.insert('1.0', AUDIO_HELP_TEXT)
        self.text_widget.config(state='disabled')
