
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles

logger = logging.getLogger("ConfigManager")


class ConfigManager:

    def __init__(self):
        self.lock = asyncio.Lock()

    def read_config(self, config_path: Path) -> Dict[str, str]:
        """Synchronous wrapper for read_config_async. Use in non-async contexts."""
        try:
            # Try to get the running event loop
            loop = asyncio.get_running_loop()
            # We're in an async context but called sync method - use asyncio.to_thread
            # This shouldn't happen in well-designed code, but provides a fallback
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self._read_config_sync, config_path)
                return future.result()
        except RuntimeError:
            # No event loop running - we're in a pure sync context
            return self._read_config_sync(config_path)

    def _read_config_sync(self, config_path: Path) -> Dict[str, str]:
        """Pure synchronous implementation for config reading."""
        config = {}

        if not config_path.exists():
            logger.debug("Config file not found: %s", config_path)
            return config

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()

                        # Remove inline comments (anything after #)
                        if '#' in value:
                            value = value.split('#')[0].strip()

                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]

                        config[key] = value

        except Exception as e:
            logger.error("Failed to read config %s: %s", config_path, e)

        return config

    async def read_config_async(self, config_path: Path) -> Dict[str, str]:
        """Async version for use in async contexts."""
        config = {}

        if not await asyncio.to_thread(config_path.exists):
            logger.debug("Config file not found: %s", config_path)
            return config

        try:
            async with aiofiles.open(config_path, 'r', encoding='utf-8') as f:
                async for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()

                        # Remove inline comments (anything after #)
                        if '#' in value:
                            value = value.split('#')[0].strip()

                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]

                        config[key] = value

        except Exception as e:
            logger.error("Failed to read config %s: %s", config_path, e)

        return config

    def write_config(self, config_path: Path, updates: Dict[str, Any]) -> bool:
        """Synchronous wrapper for write_config_async. Use in non-async contexts."""
        try:
            # Try to get the running event loop
            loop = asyncio.get_running_loop()
            # We're in an async context but called sync method - use thread pool
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self._write_config_sync, config_path, updates)
                return future.result()
        except RuntimeError:
            # No event loop running - we're in a pure sync context
            return self._write_config_sync(config_path, updates)

    def _write_config_sync(self, config_path: Path, updates: Dict[str, Any]) -> bool:
        """Pure synchronous implementation for config writing."""
        if not config_path.exists():
            logger.error("Config file not found: %s", config_path)
            return False

        # Use a simple lock for sync version (not the asyncio lock)
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            updated_keys = set()

            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue

                if '=' in stripped:
                    key = stripped.split('=')[0].strip()
                    if key in updates:
                        value = updates[key]
                        if isinstance(value, bool):
                            value_str = str(value).lower()
                        else:
                            value_str = str(value)

                        indent = len(line) - len(line.lstrip())
                        lines[i] = ' ' * indent + f"{key} = {value_str}\n"
                        updated_keys.add(key)

            for key, value in updates.items():
                if key not in updated_keys:
                    if isinstance(value, bool):
                        value_str = str(value).lower()
                    else:
                        value_str = str(value)
                    lines.append(f"{key} = {value_str}\n")
                    logger.info("Added new config key: %s = %s", key, value_str)

            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            logger.debug("Updated config file: %s (%d keys)", config_path, len(updates))
            return True

        except Exception as e:
            logger.error("Failed to write config %s: %s", config_path, e, exc_info=True)
            return False

    async def write_config_async(self, config_path: Path, updates: Dict[str, Any]) -> bool:
        """Async version for use in async contexts."""
        if not await asyncio.to_thread(config_path.exists):
            logger.error("Config file not found: %s", config_path)
            return False

        async with self.lock:
            try:
                async with aiofiles.open(config_path, 'r', encoding='utf-8') as f:
                    lines = await f.readlines()

                updated_keys = set()

                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        continue

                    if '=' in stripped:
                        key = stripped.split('=')[0].strip()
                        if key in updates:
                            value = updates[key]
                            if isinstance(value, bool):
                                value_str = str(value).lower()
                            else:
                                value_str = str(value)

                            indent = len(line) - len(line.lstrip())
                            lines[i] = ' ' * indent + f"{key} = {value_str}\n"
                            updated_keys.add(key)

                for key, value in updates.items():
                    if key not in updated_keys:
                        if isinstance(value, bool):
                            value_str = str(value).lower()
                        else:
                            value_str = str(value)
                        lines.append(f"{key} = {value_str}\n")
                        logger.info("Added new config key: %s = %s", key, value_str)

                async with aiofiles.open(config_path, 'w', encoding='utf-8') as f:
                    await f.writelines(lines)

                logger.debug("Updated config file: %s (%d keys)", config_path, len(updates))
                return True

            except Exception as e:
                logger.error("Failed to write config %s: %s", config_path, e, exc_info=True)
                return False

    def get_bool(self, config: Dict[str, str], key: str, default: bool = False) -> bool:
        if key not in config:
            return default

        value = config[key].lower()
        return value in ('true', '1', 'yes', 'on')

    def get_int(self, config: Dict[str, str], key: str, default: int = 0) -> int:
        if key not in config:
            return default

        try:
            return int(config[key])
        except ValueError:
            logger.warning("Invalid int value for %s: %s, using default %d", key, config[key], default)
            return default

    def get_float(self, config: Dict[str, str], key: str, default: float = 0.0) -> float:
        if key not in config:
            return default

        try:
            return float(config[key])
        except ValueError:
            logger.warning("Invalid float value for %s: %s, using default %f", key, config[key], default)
            return default

    def get_str(self, config: Dict[str, str], key: str, default: str = "") -> str:
        return config.get(key, default)


_config_manager = ConfigManager()


def get_config_manager() -> ConfigManager:
    return _config_manager


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    from pathlib import Path
    import tempfile

    test_config = """#################################

enabled = true
sample_rate = 48000

window_x = 100
window_y = 100
window_width = 800
window_height = 600
"""

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write(test_config)
        test_path = Path(f.name)

    cm = ConfigManager()

    config = cm.read_config(test_path)
    print("Original config:", config)

    print(f"enabled (bool): {cm.get_bool(config, 'enabled')}")
    print(f"sample_rate (int): {cm.get_int(config, 'sample_rate')}")
    print(f"window_x (int): {cm.get_int(config, 'window_x')}")

    updates = {
        'enabled': False,
        'window_x': 200,
        'window_y': 200,
        'new_key': 'test_value'
    }
    cm.write_config(test_path, updates)

    config2 = cm.read_config(test_path)
    print("\nUpdated config:", config2)

    test_path.unlink()