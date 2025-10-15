#!/usr/bin/env python3
"""
Configuration file loader for eye tracker system.

Loads and parses config.txt file with key=value syntax.
"""

import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads configuration from config.txt file."""

    @staticmethod
    def load(config_path: Path) -> Dict[str, Any]:
        """
        Load configuration from file.

        Args:
            config_path: Path to config.txt file

        Returns:
            Dictionary of configuration key-value pairs
        """
        config = {}

        if not config_path.exists():
            logger.debug("Config file not found: %s", config_path)
            return config

        logger.debug("Loading config from: %s", config_path)

        try:
            with open(config_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()

                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue

                    # Parse key=value
                    if '=' not in line:
                        logger.warning(
                            "Invalid config line %d (missing '='): %s",
                            line_num, line
                        )
                        continue

                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    # Remove inline comments
                    if '#' in value:
                        value = value.split('#', 1)[0].strip()

                    # Type conversion
                    config[key] = ConfigLoader._parse_value(value)

            logger.debug("Loaded %d config values", len(config))
            return config

        except Exception as e:
            logger.error("Failed to load config file: %s", e)
            return {}

    @staticmethod
    def _parse_value(value: str) -> Any:
        """
        Parse string value to appropriate type.

        Args:
            value: String value from config file

        Returns:
            Parsed value (bool, int, float, or str)
        """
        # Boolean
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'

        # Integer
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
