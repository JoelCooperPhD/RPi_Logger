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
   • Green bars: Normal levels (below -12 dB)
   • Yellow bars: Moderate levels (-12 to -6 dB)
   • Red bars: High levels / clipping (above -6 dB)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. OUTPUT FILES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File Naming Convention
   {timestamp}_AUDIO_trial{NNN}_{device_id}_{device_name}.wav
   {timestamp}_AUDIOTIMING_trial{NNN}_{device_id}_{device_name}.csv

   Example: 20251208_143022_AUDIO_trial001_0_usb-microphone.wav

Location
   {session_dir}/Audio/

WAV Audio File
   Format:     PCM (uncompressed)
   Bit Depth:  16-bit signed integer
   Channels:   Mono (1 channel)
   Sample Rate: 48,000 Hz default (8-192 kHz supported)

   Multi-channel devices are downmixed to mono (first channel).


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. TIMING CSV FIELD REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The AUDIOTIMING CSV contains per-chunk timing data for precise
synchronization with other modules.

CSV Columns:
   Module              - Always "Audio"
   trial               - Trial number (integer)
   write_time_unix     - System time when written (Unix seconds)
   chunk_index         - Sequential chunk number (1-based)
   write_time_monotonic - Monotonic time (seconds, 9 decimals)
   adc_timestamp       - Hardware ADC timestamp (seconds, 9 decimals)
   frames              - Audio frames in this chunk
   total_frames        - Cumulative frame count

Example Row:
   Audio,1,1702080123.456789,1,12.345678901,12.345678901,2048,2048


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. TIMING & SYNCHRONIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Timestamp Types (3 independent sources per chunk):

   write_time_unix      - System clock (may drift/jump)
                          Precision: microseconds (6 decimals)

   write_time_monotonic - Monotonic clock (never decreases)
                          Precision: nanoseconds (9 decimals)
                          Best for relative timing calculations

   adc_timestamp        - Hardware ADC timestamp from device
                          Precision: nanoseconds (9 decimals)
                          Most accurate for sample-level sync
                          May be empty if device doesn't support

Timing Accuracy
   • Timestamps recorded per audio chunk (typically 1024-4096 samples)
   • Frame counts allow sample-accurate duration calculation
   • Use total_frames / sample_rate for precise elapsed time

Calculating Audio Position
   To find the exact time of any sample:
   1. Find the chunk containing that sample (use total_frames)
   2. Use write_time_monotonic for that chunk
   3. Offset by (sample_position_in_chunk / sample_rate)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Sample Rate
   Default: 48,000 Hz
   Range: 8 kHz to 192 kHz (device-dependent)
   Higher rates = better quality but larger files

Channels
   Fixed: Mono (1 channel)
   Multi-channel inputs use first channel only


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

Empty adc_timestamp in CSV:
   This is normal - not all audio devices provide hardware timestamps.
   Use write_time_monotonic for synchronization instead.


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
