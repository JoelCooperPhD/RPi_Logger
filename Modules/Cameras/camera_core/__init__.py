"""
Camera Core Package

Core modules for the multi-camera recording system.
"""

from .camera_utils import (
    load_config_file,
    RollingFPS,
    FrameTimingMetadata,
)
from .camera_recorder import CameraRecordingManager
from .camera_handler import CameraHandler
from .camera_system import CameraSystem, CameraInitializationError
from .camera_supervisor import CameraSupervisor

__all__ = [
    # Utilities
    'load_config_file',
    'RollingFPS',
    'FrameTimingMetadata',

    # Core classes
    'CameraRecordingManager',
    'CameraHandler',
    'CameraSystem',
    'CameraInitializationError',
    'CameraSupervisor',
]
