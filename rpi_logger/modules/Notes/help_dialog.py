"""
Notes Module Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


NOTES_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
                   NOTES MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW

The Notes module allows you to add timestamped annotations during
experiment sessions. Notes are synchronized with other data streams
and saved to a CSV file for later analysis.

Use notes to mark events, observations, or participant comments.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Enable the Notes module from the Modules menu
   2. Start a session from the main logger
   3. Type your note in the text field
   4. Press Enter or click "Post" to save


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

History Panel
   Displays previously entered notes:
   • Timestamp: When the note was created
   • Elapsed Time: Time since recording started
   • Module Tags: Which modules were recording
   • Note Content: Your annotation text

New Note Field
   • Type your annotation text
   • Press Enter to submit (Shift+Enter for newline)
   • Click "Post" button to save

Color Coding
   • Blue timestamps show ISO date/time
   • Green text shows elapsed session time
   • Purple tags show active recording modules


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. RECORDING NOTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Adding a Note
   1. Type your observation in the text field
   2. Press Enter or click "Post"
   3. Note appears in history with timestamp
   4. Data is immediately saved to file

Note Content Tips
   • Keep notes brief and descriptive
   • Use consistent terminology
   • Include relevant trial or condition info
   • Note unexpected events or errors

Auto-Recording
   Notes recording starts automatically when:
   • A session is active
   • You type and submit a note


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. OUTPUT FILES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File Naming Convention
   {timestamp}_NOTES_trial{NNN}.csv

   Example: 20251208_143022_NOTES_trial001.csv

Location
   {session_dir}/Notes/


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4.5. CSV FIELD REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Notes CSV Columns (4 fields):
   Note              - Row identifier (always "Note")
   trial             - Trial number (integer, 1-based)
   Content           - User annotation text (string)
   Timestamp         - Unix timestamp (seconds, 6 decimals)

Example Row:
   Note,1,Participant started task,1733649123.456789


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4.6. TIMING & SYNCHRONIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Timestamp Precision
   Unix timestamp:     Microsecond precision (6 decimals)
   Recorded at:        Moment user presses Enter/Post

Cross-Module Synchronization
   Use Timestamp to correlate notes with:
   • Video frames (via camera capture_time_unix)
   • Audio samples (via audio write_time_unix)
   • DRT trials (via Unix time in UTC)
   • Eye tracking data (via record_time_unix)
   • GPS position (via timestamp_unix)

Example: Finding video frame for a note
   1. Read note Timestamp (e.g., 1733649123.456789)
   2. Search camera timing CSV for nearest capture_time_unix
   3. Use frame_index to locate frame in video file


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

History Limit
   Maximum notes displayed in the history panel.
   Default: 200 notes

Auto-Start
   Automatically begin recording when session starts.
   Configurable in module preferences.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. BEST PRACTICES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

During Experiments
   • Note start/end of conditions or trials
   • Record participant comments verbatim
   • Mark equipment issues or interruptions
   • Document environmental changes

For Analysis
   • Use consistent note formats
   • Include trial/condition identifiers
   • Timestamp critical events
   • Note anything unusual


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════

Notes not saving:
   1. Verify a session is active
   2. Check the session directory is writable
   3. Start session from main logger first
   4. Review module logs for errors

History not updating:
   1. Notes appear after pressing Enter/Post
   2. Check that note field is not empty
   3. Scroll to bottom of history panel
   4. Restart module if display freezes

Session required message:
   1. Start a session from the main Logger
   2. Use "Start Session" button first
   3. Then add notes during recording

Lost notes after crash:
   • Notes are saved immediately to disk
   • Check session directory for CSV file
   • Partial data should be recoverable


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

        title_label = ttk.Label(
            main_frame,
            text="Notes Quick Start Guide"
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
        self.text_widget.insert('1.0', NOTES_HELP_TEXT)
        self.text_widget.config(state='disabled')
