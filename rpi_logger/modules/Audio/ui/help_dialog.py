"""
Audio Module Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


AUDIO_HELP_TEXT = """
AUDIO MODULE QUICK START GUIDE

Records synchronized audio from USB microphones during sessions.
Device is auto-assigned by the main logger.

1. GETTING STARTED
   1. Connect USB microphone
   2. Enable Audio module from Modules menu
   3. Wait for device assignment (level meter appears)
   4. Start session to begin recording

2. LEVEL METERS
   Green:  Normal (<-12 dB)
   Yellow: Moderate (-12 to -6 dB)
   Red:    High/clipping (>-6 dB)

3. OUTPUT FILES
   Location: {session_dir}/Audio/
   Files:    {prefix}_MIC{id}_{name}.wav, *_timing.csv
   Format:   16-bit PCM mono, 48kHz default (8-192kHz)

4. TIMING CSV COLUMNS
   trial, module, device_id, label
   record_time_unix/mono - Host capture time (mono best for sync)
   write_time_unix/mono  - Host write time
   device_time_unix/seconds - Hardware timestamp (may be empty)
   chunk_index, frames, total_frames

5. CONFIGURATION
   Sample Rate: 48kHz default, 8-192kHz range
   Channels: Mono (multi-channel uses first channel)

6. TROUBLESHOOTING
   Device not assigned: Check USB, power, system audio, restart module
   No audio: Check meter levels, verify mic not muted
   Empty device_time: Normal - use record_time_mono for sync
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
