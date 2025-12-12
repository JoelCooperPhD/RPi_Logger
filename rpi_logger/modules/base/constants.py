"""
Shared constants used across multiple modules.

This module contains constants that are common to multiple modules
to avoid duplication and ensure consistency.
"""

# Audio-Video synchronization and muxing
AV_MUXING_TIMEOUT_SECONDS = 60           # Timeout for ffmpeg muxing operations
AV_DELETE_SOURCE_FILES = False           # Delete original audio/video files after muxing
