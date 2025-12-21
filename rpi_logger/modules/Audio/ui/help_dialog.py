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

The Audio module records synchronized audio from a USB microphone
during experiment sessions. It operates with a single audio input
device assigned by the main logger and provides real-time level
monitoring to help you verify audio is being captured correctly.

The device is discovered and assigned by the main logger - no manual
device selection is needed.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Connect your USB microphone
   2. Enable the Audio module from the Modules menu
   3. Wait for automatic device assignment (level meter appears when ready)
   4. Start a session to begin recording


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Device Assignment
   The audio device is automatically assigned by the main logger when
   the module starts. When a device is assigned, a level meter appears
   in the control panel. Only one audio device is supported per Audio
   module instance.

Level Meters
   Real-time audio level visualization:
   • Green bars: Normal levels (below -12 dB)
   • Yellow bars: Moderate levels (-12 to -6 dB)
   • Red bars: High levels / clipping (above -6 dB)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. OUTPUT FILES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File Naming Convention
   {prefix}_MIC{id}_{device_name}.wav
   {prefix}_MIC{id}_{device_name}_timing.csv

   Example: 20251208_143022_AUD_trial001_MIC0_usb-microphone.wav

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

The audio timing CSV contains per-chunk timing data for precise
synchronization with other modules.

CSV Columns:
   module              - Module name ("Audio")
   trial               - Trial number (integer)
   device_id           - Device identifier (integer index)
   label               - Device name
   device_time_unix    - Device absolute time (Unix seconds, if available)
   device_time_seconds - Hardware ADC timestamp (seconds)
   record_time_unix    - Host capture time (Unix seconds)
   record_time_mono    - Host capture time (seconds, 9 decimals)
   write_time_unix     - Host write time (Unix seconds)
   write_time_mono     - Host write time (seconds, 9 decimals)
   chunk_index         - Sequential chunk number (1-based)
   frames              - Audio frames in this chunk
   total_frames        - Cumulative frame count

Example Row:
   Audio,1,0,usb-microphone,,12.345678901,1702080123.456789,12.345678901,1702080123.457123,12.346012345,1,2048,2048


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. TIMING & SYNCHRONIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Timestamp Types (capture + write + device):

   record_time_unix     - Host capture clock (may drift/jump)
                          Precision: microseconds (6 decimals)

   record_time_mono     - Host monotonic capture clock (never decreases)
                          Precision: nanoseconds (9 decimals)
                          Best for relative timing calculations

   write_time_unix      - Host write clock (disk I/O timing)
                          Precision: microseconds (6 decimals)

   write_time_mono      - Host monotonic write clock
                          Precision: nanoseconds (9 decimals)

   device_time_seconds  - Hardware ADC timestamp from device
                          Precision: device-dependent
                          May be empty if device doesn't support

   device_time_unix     - Device absolute time (Unix seconds, if available)

Timing Accuracy
   • Timestamps recorded per audio chunk (typically 1024-4096 samples)
   • Frame counts allow sample-accurate duration calculation
   • Use total_frames / sample_rate for precise elapsed time

Calculating Audio Position
   To find the exact time of any sample:
   1. Find the chunk containing that sample (use total_frames)
   2. Use record_time_mono for that chunk
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

Device not assigned:
   1. Check USB connection
   2. Verify device is powered on
   3. Check system audio settings to confirm the device is recognized
   4. Verify the main logger has discovered the device
   5. Restart the module to trigger re-assignment

No audio in recording:
   1. Check input levels in the meter display - should show activity when you speak
   2. Verify microphone is not muted (check physical switches)
   3. Check system audio input settings
   4. Verify the correct device is assigned as the input source

Level meter shows no activity:
   1. Speak into the microphone or tap it gently
   2. Check physical mute switches on the microphone
   3. Verify the correct device is assigned
   4. Restart the module

Empty device_time_unix or device_time_seconds in CSV:
   This is normal - not all audio devices provide hardware timestamps.
   Use record_time_mono for synchronization instead.


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
