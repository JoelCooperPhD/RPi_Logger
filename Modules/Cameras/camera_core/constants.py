#!/usr/bin/env python3
"""
Constants for camera system.

Centralizes magic numbers and configuration values used throughout the camera module.
"""

# Frame timing validation
FRAME_DURATION_MIN_US = 1000  # 1000 FPS maximum
FRAME_DURATION_MAX_US = 10_000_000  # 0.1 FPS minimum
FPS_MIN = 0.1
FPS_MAX = 1000.0

# Hardware limits
CAMERA_FPS_MIN = 1.0
CAMERA_FPS_MAX = 60.0  # IMX296 max at 1456x1088

# Thread pool
DEFAULT_EXECUTOR_WORKERS = 4

# Timeouts (seconds)
CLEANUP_TIMEOUT_SECONDS = 2.0
THREAD_JOIN_TIMEOUT_SECONDS = 3.0
CSV_LOGGER_STOP_TIMEOUT_SECONDS = 5.0
FFMPEG_TIMEOUT_SECONDS = 60

# Recording
DEFAULT_BITRATE_BPS = 10_000_000  # 10 Mbps
CSV_FLUSH_INTERVAL_FRAMES = 60
CSV_QUEUE_SIZE = 300

# Polling intervals (seconds)
PROCESSOR_POLL_INTERVAL = 0.001  # 1ms
CAPTURE_SLEEP_INTERVAL = 0.1  # 100ms on error

# Error message sanitization
MAX_ERROR_MESSAGE_LENGTH = 200

# Frame logging
FRAME_LOG_COUNT = 3  # Log first N frames for debugging
