"""
Camera Core Package

Core modules for the multi-camera recording system.
"""

from .camera_utils import (
    RollingFPS,
    FrameTimingMetadata,
    load_config_file as load_config_file_legacy,
)
from .recording import CameraRecordingManager
from .camera_handler import CameraHandler
from .camera_system import CameraSystem, CameraInitializationError
from .camera_supervisor import CameraSupervisor

# Configuration
from .config import ConfigLoader, load_config_file, CameraConfig

# Commands
from .commands import CommandHandler, CommandMessage, StatusMessage

# Operational Modes
from .modes import BaseMode, GUIMode, SlaveMode, HeadlessMode

# User Interfaces
from .interfaces import TkinterGUI

# Display Utilities
from .display import FrameCache, CameraOverlay

__all__ = [
    # Utilities
    'RollingFPS',
    'FrameTimingMetadata',

    # Core classes
    'CameraRecordingManager',
    'CameraHandler',
    'CameraSystem',
    'CameraInitializationError',
    'CameraSupervisor',

    # Configuration
    'ConfigLoader',
    'load_config_file',
    'CameraConfig',

    # Commands
    'CommandHandler',
    'CommandMessage',
    'StatusMessage',

    # Modes
    'BaseMode',
    'GUIMode',
    'SlaveMode',
    'HeadlessMode',

    # Interfaces
    'TkinterGUI',

    # Display
    'FrameCache',
    'CameraOverlay',
]
