"""
Shared metadata structures for all RPi Logger modules.

This module defines common data structures used across Eye Tracker, Cameras,
and future modules to ensure consistent data representation.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any


class DeviceType(Enum):
    """Type of capture device"""
    CAMERA = "camera"
    EYE_TRACKER = "eye_tracker"
    AUDIO = "audio"
    IMU = "imu"
    GPS = "gps"
    CAN_BUS = "can_bus"


@dataclass
class FrameMetadata:
    """
    Universal frame/sample metadata across all capture devices.

    This is the canonical metadata structure used throughout RPi Logger.
    All modules should populate this structure when writing data.

    Required fields are common to all devices.
    Optional fields may not be available depending on hardware.
    Device-specific data goes in 'extras' dict.
    """
    # === Required Fields ===
    device_type: DeviceType
    device_id: str                      # e.g., "camera_0", "eye_tracker", "audio"
    frame_index: int                    # Sequential frame number (0-based)
    timestamp_unix: float               # Unix timestamp (seconds since epoch)
    timestamp_monotonic: float          # Monotonic clock (for interval measurement)

    # === Frame Rate ===
    fps_actual: float                   # Actual measured FPS
    fps_target: float                   # Target/configured FPS

    # === Drop Detection ===
    dropped_frames_cumulative: int = 0  # Total frames dropped since start
    dropped_frames_since_last: int = 0  # Frames dropped since last sample

    # === Optional Hardware Timestamps ===
    sensor_timestamp_ns: Optional[int] = None  # Nanosecond hardware timestamp

    # === Recording Context ===
    session_dir: Optional[Path] = None
    trial_number: Optional[int] = None
    experiment_label: Optional[str] = None

    # === Device-Specific Extensions ===
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary (for JSON serialization)"""
        return {
            'device_type': self.device_type.value,
            'device_id': self.device_id,
            'frame_index': self.frame_index,
            'timestamp_unix': self.timestamp_unix,
            'timestamp_monotonic': self.timestamp_monotonic,
            'fps_actual': self.fps_actual,
            'fps_target': self.fps_target,
            'dropped_frames_cumulative': self.dropped_frames_cumulative,
            'dropped_frames_since_last': self.dropped_frames_since_last,
            'sensor_timestamp_ns': self.sensor_timestamp_ns,
            'session_dir': str(self.session_dir) if self.session_dir else None,
            'trial_number': self.trial_number,
            'experiment_label': self.experiment_label,
            'extras': self.extras,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'FrameMetadata':
        """Create from dictionary (for JSON deserialization)"""
        data = data.copy()
        data['device_type'] = DeviceType(data['device_type'])
        if data.get('session_dir'):
            data['session_dir'] = Path(data['session_dir'])
        return cls(**data)


@dataclass
class GazeMetadata(FrameMetadata):
    """
    Extended metadata for eye tracker with gaze-specific fields.

    Inherits all standard FrameMetadata fields and adds gaze-specific data.
    """
    gaze_x: Optional[float] = None           # Normalized gaze X [0-1]
    gaze_y: Optional[float] = None           # Normalized gaze Y [0-1]
    gaze_timestamp: Optional[float] = None   # Gaze data timestamp
    pupil_diameter_left: Optional[float] = None
    pupil_diameter_right: Optional[float] = None


@dataclass
class CameraMetadata(FrameMetadata):
    """
    Extended metadata for camera with camera-specific fields.

    Inherits all standard FrameMetadata fields and adds camera-specific data.
    """
    resolution_width: int = 0
    resolution_height: int = 0
    hardware_frame_number: Optional[int] = None  # Frame number from camera hardware
    encoding_format: str = "h264"                 # Video encoding format
