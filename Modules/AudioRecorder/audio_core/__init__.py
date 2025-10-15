"""
Audio Core Package

Core modules for the multi-microphone audio recording system.
"""

from .audio_utils import DeviceDiscovery
from .recording import AudioRecordingManager
from .audio_handler import AudioHandler
from .audio_system import AudioSystem, AudioInitializationError
from .audio_supervisor import AudioSupervisor

# Modular components
from .config import ConfigLoader, load_config_file
from .commands import CommandHandler, CommandMessage, StatusMessage
from .modes import BaseMode, SlaveMode, HeadlessMode, GUIMode

__all__ = [
    # Utilities
    'DeviceDiscovery',

    # Core classes
    'AudioRecordingManager',
    'AudioHandler',
    'AudioSystem',
    'AudioInitializationError',
    'AudioSupervisor',

    # Configuration
    'ConfigLoader',
    'load_config_file',

    # Commands
    'CommandHandler',
    'CommandMessage',
    'StatusMessage',

    # Modes
    'BaseMode',
    'SlaveMode',
    'HeadlessMode',
    'GUIMode',
]
