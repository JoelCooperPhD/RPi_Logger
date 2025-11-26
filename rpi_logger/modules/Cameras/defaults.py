"""
Shared default values for the Cameras module.

Keep this module lightweight - it's imported by worker subprocesses.
"""

DEFAULT_CAPTURE_RESOLUTION = (1280, 720)
DEFAULT_CAPTURE_FPS = 30.0
DEFAULT_RECORD_FPS = 30.0
DEFAULT_PREVIEW_SIZE = (320, 180)
DEFAULT_PREVIEW_FPS = 10.0
DEFAULT_PREVIEW_JPEG_QUALITY = 80
