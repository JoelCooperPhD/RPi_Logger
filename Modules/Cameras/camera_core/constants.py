# Import shared constants from base module
from Modules.base.constants import (
    CLEANUP_TIMEOUT_SECONDS,
    MAX_ERROR_MESSAGE_LENGTH,
)

# Frame timing validation
FRAME_DURATION_MIN_US = 1000  # 1000 FPS maximum
FRAME_DURATION_MAX_US = 10_000_000  # 0.1 FPS minimum
FPS_MIN = 0.1
FPS_MAX = 1000.0

CAMERA_FPS_MIN = 1.0
CAMERA_FPS_MAX = 60.0  # IMX296 max at 1456x1088

DEFAULT_EXECUTOR_WORKERS = 4

# Module-specific timeouts
THREAD_JOIN_TIMEOUT_SECONDS = 3.0
CSV_LOGGER_STOP_TIMEOUT_SECONDS = 5.0
FFMPEG_TIMEOUT_SECONDS = 60

DEFAULT_BITRATE_BPS = 10_000_000  # 10 Mbps
CSV_FLUSH_INTERVAL_FRAMES = 60
CSV_QUEUE_SIZE = 300

# NOTE: PROCESSOR_POLL_INTERVAL is deprecated - processor now uses event-driven coordination
PROCESSOR_POLL_INTERVAL = 0.001  # 1ms (DEPRECATED - kept for reference)
CAPTURE_SLEEP_INTERVAL = 0.1  # 100ms on error

FRAME_LOG_COUNT = 3  # Log first N frames for debugging
