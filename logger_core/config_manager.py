#!/usr/bin/env python3
"""
Configuration Manager

Handles reading and writing of module configuration files while preserving
comments and formatting.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("ConfigManager")


class ConfigManager:
    """
    Manages module configuration files.

    Features:
    - Read/write config files
    - Preserve comments and formatting
    - Thread-safe updates
    - Type conversion (bool, int, float, str)
    """

    def __init__(self):
        """Initialize config manager."""
        self.lock = threading.Lock()

    def read_config(self, config_path: Path) -> Dict[str, str]:
        """
        Read configuration from a config.txt file.

        Args:
            config_path: Path to config file

        Returns:
            Dict of config key-value pairs (all values as strings)
        """
        config = {}

        if not config_path.exists():
            logger.debug("Config file not found: %s", config_path)
            return config

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    # Parse key = value
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()

                        # Remove inline comments (anything after #)
                        if '#' in value:
                            value = value.split('#')[0].strip()

                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]

                        config[key] = value

        except Exception as e:
            logger.error("Failed to read config %s: %s", config_path, e)

        return config

    def write_config(self, config_path: Path, updates: Dict[str, Any]) -> bool:
        """
        Update configuration file with new values while preserving comments.

        Args:
            config_path: Path to config file
            updates: Dict of keys to update with new values

        Returns:
            True if successful, False otherwise
        """
        if not config_path.exists():
            logger.error("Config file not found: %s", config_path)
            return False

        with self.lock:
            try:
                # Read all lines
                with open(config_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                # Track which keys were updated
                updated_keys = set()

                # Update existing keys
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        continue

                    if '=' in stripped:
                        key = stripped.split('=')[0].strip()
                        if key in updates:
                            # Update this line
                            value = updates[key]
                            # Convert value to string
                            if isinstance(value, bool):
                                value_str = str(value).lower()
                            else:
                                value_str = str(value)

                            # Preserve indentation
                            indent = len(line) - len(line.lstrip())
                            lines[i] = ' ' * indent + f"{key} = {value_str}\n"
                            updated_keys.add(key)

                # Add any keys that weren't found (append to end)
                for key, value in updates.items():
                    if key not in updated_keys:
                        if isinstance(value, bool):
                            value_str = str(value).lower()
                        else:
                            value_str = str(value)
                        lines.append(f"{key} = {value_str}\n")
                        logger.info("Added new config key: %s = %s", key, value_str)

                # Write back to file
                with open(config_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)

                logger.debug("Updated config file: %s (%d keys)", config_path, len(updates))
                return True

            except Exception as e:
                logger.error("Failed to write config %s: %s", config_path, e, exc_info=True)
                return False

    def get_bool(self, config: Dict[str, str], key: str, default: bool = False) -> bool:
        """
        Get boolean value from config.

        Args:
            config: Config dict
            key: Config key
            default: Default value if key not found

        Returns:
            Boolean value
        """
        if key not in config:
            return default

        value = config[key].lower()
        return value in ('true', '1', 'yes', 'on')

    def get_int(self, config: Dict[str, str], key: str, default: int = 0) -> int:
        """
        Get integer value from config.

        Args:
            config: Config dict
            key: Config key
            default: Default value if key not found

        Returns:
            Integer value
        """
        if key not in config:
            return default

        try:
            return int(config[key])
        except ValueError:
            logger.warning("Invalid int value for %s: %s, using default %d", key, config[key], default)
            return default

    def get_float(self, config: Dict[str, str], key: str, default: float = 0.0) -> float:
        """
        Get float value from config.

        Args:
            config: Config dict
            key: Config key
            default: Default value if key not found

        Returns:
            Float value
        """
        if key not in config:
            return default

        try:
            return float(config[key])
        except ValueError:
            logger.warning("Invalid float value for %s: %s, using default %f", key, config[key], default)
            return default

    def get_str(self, config: Dict[str, str], key: str, default: str = "") -> str:
        """
        Get string value from config.

        Args:
            config: Config dict
            key: Config key
            default: Default value if key not found

        Returns:
            String value
        """
        return config.get(key, default)


# Global instance
_config_manager = ConfigManager()


def get_config_manager() -> ConfigManager:
    """Get the global ConfigManager instance."""
    return _config_manager


if __name__ == "__main__":
    # Test the config manager
    logging.basicConfig(level=logging.DEBUG)

    from pathlib import Path
    import tempfile

    # Create a test config file
    test_config = """#################################
# TEST CONFIGURATION
#################################

# Recording settings
enabled = true
sample_rate = 48000

# Window settings
window_x = 100
window_y = 100
window_width = 800
window_height = 600
"""

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write(test_config)
        test_path = Path(f.name)

    cm = ConfigManager()

    # Read config
    config = cm.read_config(test_path)
    print("Original config:", config)

    # Test type conversions
    print(f"enabled (bool): {cm.get_bool(config, 'enabled')}")
    print(f"sample_rate (int): {cm.get_int(config, 'sample_rate')}")
    print(f"window_x (int): {cm.get_int(config, 'window_x')}")

    # Update config
    updates = {
        'enabled': False,
        'window_x': 200,
        'window_y': 200,
        'new_key': 'test_value'
    }
    cm.write_config(test_path, updates)

    # Read again
    config2 = cm.read_config(test_path)
    print("\nUpdated config:", config2)

    # Cleanup
    test_path.unlink()
