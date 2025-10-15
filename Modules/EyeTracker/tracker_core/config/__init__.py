"""
Configuration management for eye tracker system.
"""

from .config_loader import ConfigLoader, load_config_file
from .tracker_config import TrackerConfig

__all__ = [
    'ConfigLoader',
    'load_config_file',
    'TrackerConfig',
]
