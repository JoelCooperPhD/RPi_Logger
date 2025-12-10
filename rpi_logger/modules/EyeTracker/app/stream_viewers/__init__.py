"""Stream viewer widgets for the EyeTracker module.

This package provides viewer widgets for each RTSP stream from the Neon eye tracker:
- VideoViewer: Main scene camera preview with optional gaze overlay
- EyesViewer: Dual eye camera display
- IMUViewer: Numeric accelerometer/gyroscope display
- EventsViewer: Eye event counters (blinks, fixations, saccades)
- AudioViewer: Audio level meter
- StreamControls: Checkbox management for enabling/disabling streams
"""

from .base_viewer import BaseStreamViewer
from .video_viewer import VideoViewer
from .eyes_viewer import EyesViewer
from .imu_viewer import IMUViewer
from .events_viewer import EventsViewer
from .audio_viewer import AudioViewer
from .stream_controls import StreamControls

__all__ = [
    "BaseStreamViewer",
    "VideoViewer",
    "EyesViewer",
    "IMUViewer",
    "EventsViewer",
    "AudioViewer",
    "StreamControls",
]
