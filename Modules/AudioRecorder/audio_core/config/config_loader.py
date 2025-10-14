#!/usr/bin/env python3
"""
Configuration file loader for audio recording system.

Loads settings from config.txt with support for:
- Sample rate configuration
- Output directory settings
- Logging configuration
- Auto-start options
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("ConfigLoader")


class ConfigLoader:
    """Handles loading and parsing of config.txt file."""

    @staticmethod
    def load_config(config_path: Path) -> Dict[str, Any]:
        """
        Load configuration from config.txt file.

        Args:
            config_path: Path to config.txt file

        Returns:
            Dictionary of configuration key-value pairs
        """
        config = {}

        if not config_path.exists():
            logger.debug("No config file found at %s", config_path)
            return config

        try:
            with open(config_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    # Strip whitespace and skip comments/empty lines
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    # Parse key = value
                    if '=' not in line:
                        logger.warning("Invalid config line %d: %s", line_num, line)
                        continue

                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    # Remove inline comments (everything after #)
                    if '#' in value:
                        value = value.split('#')[0].strip()

                    # Parse value types
                    config[key] = ConfigLoader._parse_value(value)

            logger.info("Loaded config from %s (%d settings)", config_path, len(config))
            return config

        except Exception as e:
            logger.error("Error loading config file: %s", e)
            return {}

    @staticmethod
    def _parse_value(value: str) -> Any:
        """
        Parse configuration value to appropriate type.

        Args:
            value: String value from config file

        Returns:
            Parsed value (bool, int, float, or str)
        """
        value_lower = value.lower()

        # Boolean
        if value_lower in ('true', 'false'):
            return value_lower == 'true'

        # Integer (more robust parsing with try/except)
        try:
            return int(value)
        except ValueError:
            pass

        # Float
        try:
            return float(value)
        except ValueError:
            pass

        # String (default)
        return value


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
