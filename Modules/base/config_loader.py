#!/usr/bin/env python3
"""
Unified Configuration Loader for all modules.

Provides consistent config file parsing with key=value syntax,
comment handling, and type conversion.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ConfigLoader:
    """
    Unified configuration file loader.

    Supports:
    - key=value syntax
    - Comments (lines starting with # and inline comments)
    - Automatic type conversion (bool, int, float, string)
    - Default value merging
    """

    @staticmethod
    def load(
        config_path: Path,
        defaults: Optional[Dict[str, Any]] = None,
        strict: bool = False
    ) -> Dict[str, Any]:
        """
        Load configuration from file.

        Args:
            config_path: Path to config file
            defaults: Optional default values dictionary
            strict: If True, only accept keys that exist in defaults

        Returns:
            Dictionary of configuration values (defaults merged with file values)
        """
        # Start with defaults (or empty dict)
        config = defaults.copy() if defaults else {}

        if not config_path.exists():
            if defaults:
                logger.debug("Config file not found at %s, using defaults", config_path)
            else:
                logger.warning("Config file not found at %s and no defaults provided", config_path)
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

                    # Check if key is allowed (if strict mode and defaults provided)
                    if strict and defaults is not None and key not in defaults:
                        logger.warning(
                            "Unknown config key '%s' (line %d) - ignored in strict mode",
                            key, line_num
                        )
                        continue

                    # Type conversion (use default's type if available)
                    if defaults and key in defaults:
                        config[key] = ConfigLoader._parse_value_with_type(
                            value, type(defaults[key])
                        )
                    else:
                        config[key] = ConfigLoader._parse_value(value)

            logger.info("Loaded config from %s (%d values)", config_path, len(config))
            return config

        except Exception as e:
            logger.error("Failed to load config file: %s", e)
            return config  # Return defaults on error

    @staticmethod
    def _parse_value(value: str) -> Any:
        """
        Parse string value to appropriate type (automatic detection).

        Args:
            value: String value from config file

        Returns:
            Parsed value (bool, int, float, or str)
        """
        # Boolean
        value_lower = value.lower()
        if value_lower in ('true', 'false', 'yes', 'no', 'on', 'off', '1', '0'):
            return value_lower in ('true', 'yes', 'on', '1')

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

    @staticmethod
    def _parse_value_with_type(value: str, target_type: type) -> Any:
        """
        Parse string value to specific type.

        Args:
            value: String value from config file
            target_type: Target type to convert to

        Returns:
            Parsed value of target_type
        """
        # Boolean
        if target_type == bool:
            value_lower = value.lower()
            return value_lower in ('true', 'yes', 'on', '1')

        # Numeric types
        if target_type in (int, float):
            try:
                return target_type(value)
            except ValueError:
                logger.warning("Failed to parse '%s' as %s, using default", value, target_type.__name__)
                return target_type()  # Return 0 or 0.0

        # String (default)
        return value


def load_config_file(
    config_path: Optional[Path] = None,
    module_name: Optional[str] = None,
    defaults: Optional[Dict[str, Any]] = None,
    strict: bool = False
) -> Dict[str, Any]:
    """
    Convenience function to load configuration file.

    Args:
        config_path: Optional path to config file
        module_name: Optional module name (used to find default config.txt location)
        defaults: Optional default values dictionary
        strict: If True, only accept keys that exist in defaults

    Returns:
        Configuration dictionary
    """
    if config_path is None and module_name:
        # Auto-detect config path from module name
        # This assumes config.txt is in Modules/{module_name}/config.txt
        base_dir = Path(__file__).parent.parent
        config_path = base_dir / module_name / "config.txt"
    elif config_path is None:
        logger.warning("No config path or module name provided")
        return defaults.copy() if defaults else {}

    return ConfigLoader.load(config_path, defaults, strict)
