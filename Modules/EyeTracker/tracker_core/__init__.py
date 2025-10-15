"""
Tracker Core Package

Core modules for the eye tracking system.
"""

from .tracker_utils import RollingFPS
from .recording import RecordingManager, FrameTimingMetadata
from .tracker_system import TrackerSystem, TrackerInitializationError, TrackerConfig
from .tracker_supervisor import TrackerSupervisor

# Import components that were moved here
from .device_manager import DeviceManager
from .stream_handler import StreamHandler
from .frame_processor import FrameProcessor
from .gaze_tracker import GazeTracker

# New modular components
from .config import ConfigLoader, load_config_file
from .commands import CommandHandler, CommandMessage, StatusMessage
from .modes import BaseMode, GUIMode, SlaveMode, HeadlessMode

__all__ = [
    # Utilities
    'RollingFPS',

    # Core classes
    'RecordingManager',
    'FrameTimingMetadata',
    'TrackerSystem',
    'TrackerInitializationError',
    'TrackerConfig',
    'TrackerSupervisor',

    # Components
    'DeviceManager',
    'StreamHandler',
    'FrameProcessor',
    'GazeTracker',

    # Configuration
    'ConfigLoader',
    'load_config_file',

    # Commands
    'CommandHandler',
    'CommandMessage',
    'StatusMessage',

    # Modes
    'BaseMode',
    'GUIMode',
    'SlaveMode',
    'HeadlessMode',
]
