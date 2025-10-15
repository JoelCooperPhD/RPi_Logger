#!/usr/bin/env python3
"""
Constants for eye tracker system.

Centralizes magic numbers and configuration values used throughout the tracker module.
"""

# FPS limits
FPS_MIN = 1.0
FPS_MAX = 120.0
FPS_DEFAULT = 5.0

# Resolution limits
RESOLUTION_WIDTH_MIN = 320
RESOLUTION_WIDTH_MAX = 3840
RESOLUTION_HEIGHT_MIN = 240
RESOLUTION_HEIGHT_MAX = 2160
RESOLUTION_DEFAULT = (1280, 720)

# Preview limits
PREVIEW_WIDTH_MIN = 320
PREVIEW_WIDTH_MAX = 1920
PREVIEW_WIDTH_DEFAULT = 640

# Timeouts (seconds)
CLEANUP_TIMEOUT_SECONDS = 2.0
DEVICE_DISCOVERY_TIMEOUT = 5.0
DEVICE_DISCOVERY_RETRY = 3.0
STREAM_STOP_TIMEOUT_SECONDS = 5.0
FRAME_TIMEOUT_SECONDS = 1.0

# Polling intervals (seconds)
KEYBOARD_POLL_INTERVAL = 0.001  # 1ms for keyboard input
FRAME_PROCESS_INTERVAL = 0.0  # asyncio.sleep(0) for cooperative multitasking

# Error message sanitization
MAX_ERROR_MESSAGE_LENGTH = 200

# Recording
RECORDING_FORMAT_MP4 = "mp4"
RECORDING_FORMAT_AVI = "avi"
RECORDING_CODEC_H264 = "H264"
RECORDING_CODEC_MJPEG = "MJPEG"

# Stream buffer sizes
GAZE_QUEUE_SIZE = 100
IMU_QUEUE_SIZE = 100
EVENT_QUEUE_SIZE = 100
FRAME_QUEUE_SIZE = 10

# Feedback intervals
STATUS_UPDATE_INTERVAL_SECONDS = 2.0

# OpenCV window names
WINDOW_NAME_PREFIX = "Eye Tracker"

# Log rate limiting
FRAME_WARNING_INTERVAL = 5  # Log frame warnings every N seconds
