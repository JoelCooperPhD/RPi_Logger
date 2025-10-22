#!/usr/bin/env python3
"""
Configuration file loader for eye tracker system.

Uses unified ConfigLoader from base module.
Loads and parses config.txt file with key=value syntax.
"""

import logging
from pathlib import Path
from typing import Dict, Any

from Modules.base import ConfigLoader as BaseConfigLoader

logger = logging.getLogger(__name__)


class ConfigLoader:
    """
    Eye tracker configuration loader (wrapper for unified ConfigLoader).

    Maintains backward compatibility with existing code.
    """

    @staticmethod
    def load(config_path: Path) -> Dict[str, Any]:
        """
        Load configuration from file.

        Args:
            config_path: Path to config.txt file

        Returns:
            Dictionary of configuration key-value pairs
        """
        return BaseConfigLoader.load(config_path, defaults=None)

    @staticmethod
    def _parse_value(value: str) -> Any:
        """
        Parse string value to appropriate type.

        Deprecated: Use BaseConfigLoader._parse_value directly.
        Kept for backward compatibility.

        Args:
            value: String value from config file

        Returns:
            Parsed value (bool, int, float, or str)
        """
        return BaseConfigLoader._parse_value(value)


def load_config_file(config_path: Path = None) -> Dict[str, Any]:
    """
    Load configuration from config.txt.

    Args:
        config_path: Optional path to config file (defaults to ./config.txt)

    Returns:
        Dictionary of configuration values
    """
    if config_path is None:
        # Default to config.txt in EyeTracker module directory
        module_dir = Path(__file__).parent.parent.parent
        config_path = module_dir / "config.txt"

    return ConfigLoader.load(config_path)
