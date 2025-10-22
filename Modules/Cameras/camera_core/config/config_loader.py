#!/usr/bin/env python3
"""
Configuration file loader for camera module.

Uses unified ConfigLoader from base module.
"""

import logging
from pathlib import Path
from typing import Dict, Any

from Modules.base import ConfigLoader as BaseConfigLoader

logger = logging.getLogger("ConfigLoader")


# Default configuration values for camera module
DEFAULT_OVERLAY_CONFIG = {
    # Camera settings
    'resolution_preset': 0,
    'resolution_width': 1920,
    'resolution_height': 1080,
    'preview_preset': 5,
    'preview_width': 640,
    'preview_height': 360,
    'target_fps': 30.0,
    'min_cameras': 1,
    'allow_partial': True,
    'discovery_timeout': 5.0,
    'discovery_retry': 3.0,
    'output_dir': 'recordings',
    'session_prefix': 'session',
    'auto_start_recording': False,
    'show_preview': True,
    'console_output': False,
    'libcamera_log_level': 'WARN',
    # Overlay settings
    'font_scale_base': 0.6,
    'thickness_base': 2,
    'font_type': 'SIMPLEX',
    'outline_enabled': True,
    'outline_extra_thickness': 2,
    'line_start_y': 30,
    'line_spacing': 30,
    'margin_left': 10,
    'text_color_b': 255,
    'text_color_g': 255,
    'text_color_r': 255,
    'outline_color_b': 0,
    'outline_color_g': 0,
    'outline_color_r': 0,
    'line_type': 16,
    'background_enabled': False,
    'background_shape': 'rectangle',
    'background_color_b': 0,
    'background_color_g': 0,
    'background_color_r': 0,
    'background_opacity': 0.6,
    'background_padding_top': 10,
    'background_padding_bottom': 10,
    'background_padding_left': 10,
    'background_padding_right': 10,
    'background_corner_radius': 10,
    'show_camera_and_time': True,
    'show_session': True,
    'show_requested_fps': True,
    'show_sensor_fps': True,
    'show_display_fps': True,
    'show_frame_counter': True,
    'show_recording_info': True,
    'show_recording_filename': True,
    'show_controls': True,
    'show_frame_number': True,
    'scale_mode': 'auto',
    'manual_scale_factor': 3.0,
    # Recording settings
    'enable_csv_timing_log': True,
    'disable_mp4_conversion': True,
}


class ConfigLoader:
    """
    Camera configuration loader (wrapper for unified ConfigLoader).

    Maintains backward compatibility with existing code.
    """

    DEFAULT_OVERLAY_CONFIG = DEFAULT_OVERLAY_CONFIG

    @staticmethod
    def load_overlay_config(config_path: Path) -> Dict[str, Any]:
        """
        Load overlay configuration from file.

        Args:
            config_path: Path to config.txt file

        Returns:
            Dictionary with configuration values
        """
        return BaseConfigLoader.load(config_path, defaults=DEFAULT_OVERLAY_CONFIG)


def load_config_file(config_path: str = None) -> Dict[str, Any]:
    """
    Load configuration file from standard location.

    Args:
        config_path: Optional path to config file (defaults to ../config.txt)

    Returns:
        Dictionary with configuration values
    """
    if config_path is None:
        # Default: look for config.txt two directories up (from camera_core/config/ to Cameras/)
        config_path = Path(__file__).parents[2] / "config.txt"
    else:
        config_path = Path(config_path)

    return ConfigLoader.load_overlay_config(config_path)
