import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


NOTES_HELP_TEXT = """NOTES MODULE - QUICK START

USAGE: Enable Notes > Start session > Type note > Press Enter/click Post

UI COLORS: Blue=timestamp, Green=elapsed, Purple=modules

OUTPUT: {session_dir}/Notes/{prefix}_notes.csv
COLUMNS: trial, module, device_id, label, record_time_unix (6dp),
         record_time_mono (9dp), device_time_unix, content

CONFIG: History Limit (default 200), Auto-Start option

TIPS: Mark trial boundaries, note equipment issues, use consistent terms

TROUBLESHOOTING
- Notes not saving: Start session first
- Lost notes: Check session CSV (saved immediately)
"""


class NotesHelpDialog:
    """Dialog showing Notes quick start guide."""
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Notes Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)
        self.dialog.geometry("550x350")

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
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 275
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 175
        self.dialog.geometry(f"+{x}+{y}")
