import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


NOTES_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
                   NOTES MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW
Add timestamped annotations during sessions. Notes are synchronized with
other data streams and saved to CSV for analysis.

GETTING STARTED
1. Enable Notes from the Modules menu
2. Start a session from main logger
3. Type note and press Enter or click "Post"

USER INTERFACE
History Panel: Shows timestamp, elapsed time, module tags, content
  • Blue: ISO date/time
  • Green: Elapsed session time
  • Purple: Active recording modules

New Note Field: Enter to submit, Shift+Enter for newline

OUTPUT FILES
Format: {prefix}_notes.csv
Example: 20251208_143022_NTS_trial001_notes.csv
Location: {session_dir}/Notes/

CSV COLUMNS (8 fields)
trial, module, device_id, label, record_time_unix, record_time_mono,
device_time_unix, content

TIMING & SYNCHRONIZATION
record_time_unix: Microsecond precision (6 decimals)
record_time_mono: Nanosecond precision (9 decimals)
Use these to correlate with video frames, audio, DRT, eye tracking, GPS

CONFIGURATION
History Limit: Max notes displayed (default: 200)
Auto-Start: Begin recording with session start

BEST PRACTICES
• Mark condition/trial start/end
• Record participant comments verbatim
• Note equipment issues or interruptions
• Use consistent terminology

TROUBLESHOOTING
Notes not saving: Start session from main logger first
History not updating: Check note field not empty, scroll to bottom
Session required: Use "Start Session" button before recording
Lost notes: Check session directory CSV (saved immediately)
"""


class NotesHelpDialog:
    """Dialog showing Notes quick start guide."""
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Notes Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)
        self.dialog.geometry("700x600")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Notes Quick Start Guide").pack(pady=(0, 10))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text_widget = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, state='disabled')
        Theme.configure_scrolled_text(self.text_widget, readonly=True)
        self.text_widget.pack(fill=tk.BOTH, expand=True)

        self.text_widget.config(state='normal')
        self.text_widget.insert('1.0', NOTES_HELP_TEXT)
        self.text_widget.config(state='disabled')

        ttk.Button(ttk.Frame(main_frame).pack(pady=(10, 0)) or main_frame,
                   text="Close", command=self.dialog.destroy).pack()

        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 350
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 300
        self.dialog.geometry(f"+{x}+{y}")
