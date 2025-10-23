
MODULE_NAME = "NoteTaker"
MODULE_DESCRIPTION = "Timestamped note-taking module for car logging sessions"

DEFAULT_OUTPUT_DIR = "notes"
DEFAULT_SESSION_PREFIX = "notes"
CSV_FILENAME = "session_notes.csv"

CSV_HEADERS = ["timestamp", "session_elapsed_time", "note_text", "recording_modules"]

DEFAULT_WINDOW_WIDTH = 600
DEFAULT_WINDOW_HEIGHT = 500
MAX_DISPLAYED_NOTES = 100

# Timing
PREVIEW_UPDATE_INTERVAL = 0.5  # Update elapsed time every 500ms
