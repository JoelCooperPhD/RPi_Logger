#!/usr/bin/env python3
"""
Configuration file loader for audio recording system.

Uses unified ConfigLoader from base module.
Supports:
- Sample rate configuration
- Output directory settings
- Logging configuration
- Auto-start options
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from Modules.base import ConfigLoader as BaseConfigLoader

logger = logging.getLogger("ConfigLoader")


class ConfigLoader:
    """
    Audio configuration loader (wrapper for unified ConfigLoader).

    Maintains backward compatibility with existing code.
    """

    @staticmethod
    def load_config(config_path: Path) -> Dict[str, Any]:
        """
        Load configuration from config.txt file.

        Args:
            config_path: Path to config.txt file

        Returns:
            Dictionary of configuration key-value pairs
        """
        return BaseConfigLoader.load(config_path, defaults=None)

    @staticmethod
    def _parse_value(value: str) -> Any:
        """
        Parse configuration value to appropriate type.

        Deprecated: Use BaseConfigLoader._parse_value directly.
        Kept for backward compatibility.

        Args:
            value: String value from config file

        Returns:
            Parsed value (bool, int, float, or str)
        """
        return BaseConfigLoader._parse_value(value)


def load_config_file(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load configuration file from default or specified path.

    Args:
        config_path: Optional path to config file. If None, looks for config.txt
                    in the AudioRecorder module directory.

    Returns:
        Configuration dictionary
    """
    if config_path is None:
        # Default: look for config.txt in AudioRecorder directory
        module_dir = Path(__file__).parent.parent.parent
        config_path = module_dir / "config.txt"

    return ConfigLoader.load_config(config_path)
