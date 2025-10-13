"""
Configuration Management Package

Handles loading and managing configuration for the camera system.
"""

from .config_loader import ConfigLoader, load_config_file
from .camera_config import CameraConfig

__all__ = [
    'ConfigLoader',
    'load_config_file',
    'CameraConfig',
]
