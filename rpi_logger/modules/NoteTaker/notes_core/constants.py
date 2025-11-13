# Import shared constants from base module
from rpi_logger.modules.base.constants import (
    CLEANUP_TIMEOUT_SECONDS,
    MAX_ERROR_MESSAGE_LENGTH,
)

MODULE_NAME = "NoteTaker"
MODULE_DESCRIPTION = "Timestamped note-taking module for car logging sessions"

DEFAULT_OUTPUT_DIR = "notes"
DEFAULT_SESSION_PREFIX = "notes"
TXT_FILENAME_PATTERN = "{version}_{date}.txt"

HEADERS = "Note,Content,Timestamp"

DEFAULT_WINDOW_WIDTH = 600
DEFAULT_WINDOW_HEIGHT = 500
MAX_DISPLAYED_NOTES = 100

# Timing
PREVIEW_UPDATE_INTERVAL = 0.5  # Update elapsed time every 500ms
