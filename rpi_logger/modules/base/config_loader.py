
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ConfigLoader:

    @staticmethod
    async def load_async(
        config_path: Path,
        defaults: Optional[Dict[str, Any]] = None,
        strict: bool = False
    ) -> Dict[str, Any]:
        """Async version of load() using asyncio.to_thread for file I/O."""
        return await asyncio.to_thread(ConfigLoader.load, config_path, defaults, strict)

    @staticmethod
    def load(
        config_path: Path,
        defaults: Optional[Dict[str, Any]] = None,
        strict: bool = False
    ) -> Dict[str, Any]:
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

                    if not line or line.startswith('#'):
                        continue

                    if '=' not in line:
                        logger.warning(
                            "Invalid config line %d (missing '='): %s",
                            line_num, line
                        )
                        continue

                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    if '#' in value:
                        value = value.split('#', 1)[0].strip()

                    if strict and defaults is not None and key not in defaults:
                        logger.warning(
                            "Unknown config key '%s' (line %d) - ignored in strict mode",
                            key, line_num
                        )
                        continue

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
        value_lower = value.lower()
        if value_lower in ('true', 'false', 'yes', 'no', 'on', 'off', '1', '0'):
            return value_lower in ('true', 'yes', 'on', '1')

        try:
            return int(value)
        except ValueError:
            pass

        try:
            return float(value)
        except ValueError:
            pass

        return value

    @staticmethod
    def _parse_value_with_type(value: str, target_type: type) -> Any:
        if target_type == bool:
            value_lower = value.lower()
            return value_lower in ('true', 'yes', 'on', '1')

        if target_type is int:
            try:
                return int(value, 0)  # Support decimal, hex (0x...), octal (0o...), binary (0b...)
            except ValueError:
                logger.warning("Failed to parse '%s' as int, using default", value)
                return target_type()

        if target_type is float:
            try:
                return float(value)
            except ValueError:
                logger.warning("Failed to parse '%s' as float, using default", value)
                return target_type()

        return value

    @staticmethod
    def load_module_config(
        calling_file: str,
        config_filename: str = "config.txt",
        defaults: Optional[Dict[str, Any]] = None,
        strict: bool = False
    ) -> Dict[str, Any]:
        """
        Load a module's config file relative to the calling file's location.

        This helper allows modules to load their config.txt without hardcoding paths.
        The calling file should be __file__ from the caller's context.

        Example usage from rpi_logger.modules/Camera/camera_core/config/config_loader.py:
            config = ConfigLoader.load_module_config(__file__)

        Args:
            calling_file: The __file__ variable from the caller (used to locate module root)
            config_filename: Name of the config file (default: "config.txt")
            defaults: Optional default values
            strict: If True, only keys in defaults are accepted

        Returns:
            Dict containing config values
        """
        # Navigate up from calling_file to find module root (where config.txt lives)
        # Typical structure: rpi_logger/modules/ModuleName/module_core/config/config_loader.py
        # We need to go up 3 levels to rpi_logger/modules/ModuleName/
        calling_path = Path(calling_file)

        # Go up until we find a directory containing config_filename
        # or until we've gone up 5 levels (safety limit)
        search_path = calling_path.parent
        for _ in range(5):
            config_path = search_path / config_filename
            if config_path.exists():
                return ConfigLoader.load(config_path, defaults, strict)
            search_path = search_path.parent

        # If not found, try 3 levels up (standard module structure)
        module_root = calling_path.parent.parent.parent
        config_path = module_root / config_filename

        return ConfigLoader.load(config_path, defaults, strict)

    @staticmethod
    async def update_config_values_async(config_path: Path, updates: Dict[str, Any]) -> bool:
        """Async version of update_config_values() using asyncio.to_thread for file I/O."""
        return await asyncio.to_thread(ConfigLoader.update_config_values, config_path, updates)

    @staticmethod
    def update_config_values(config_path: Path, updates: Dict[str, Any]) -> bool:
        if not config_path.exists():
            logger.warning("Config file not found at %s, cannot update", config_path)
            return False

        try:
            with open(config_path, 'r') as f:
                lines = f.readlines()

            updated_keys = set()

            for i, line in enumerate(lines):
                stripped = line.strip()

                if not stripped or stripped.startswith('#'):
                    continue

                if '=' in stripped:
                    key = stripped.split('=', 1)[0].strip()
                    if key in updates:
                        indent = len(line) - len(line.lstrip())
                        value_str = ConfigLoader._format_config_value(updates[key])

                        if '#' in stripped.split('=', 1)[1]:
                            comment = '#' + stripped.split('#', 1)[1]
                            lines[i] = f"{' ' * indent}{key} = {value_str} {comment}\n"
                        else:
                            lines[i] = f"{' ' * indent}{key} = {value_str}\n"

                        updated_keys.add(key)

            missing_items = [
                (key, ConfigLoader._format_config_value(updates[key]))
                for key in updates
                if key not in updated_keys
            ]

            if missing_items:
                if lines and not lines[-1].endswith('\n'):
                    lines[-1] = f"{lines[-1]}\n"

                comment_text = '# Auto-generated settings (do not edit unless you know what you are doing)'
                comment_line = f"{comment_text}\n"
                has_comment = any(line.strip() == comment_text for line in lines)

                if not has_comment:
                    if lines and lines[-1].strip():
                        lines.append('\n')
                    lines.append(comment_line)

                for key, value_str in missing_items:
                    lines.append(f"{key} = {value_str}\n")

            with open(config_path, 'w') as f:
                f.writelines(lines)

            logger.info("Updated config file: %s (keys: %s)", config_path, updated_keys or {key for key, _ in missing_items})
            return True

        except Exception as e:
            logger.error("Failed to update config file: %s", e, exc_info=True)
            return False

    @staticmethod
    def _format_config_value(value: Any) -> str:
        if isinstance(value, bool):
            return 'true' if value else 'false'
        return str(value)


def load_config_file(
    config_path: Optional[Path] = None,
    module_name: Optional[str] = None,
    defaults: Optional[Dict[str, Any]] = None,
    strict: bool = False
) -> Dict[str, Any]:
    if config_path is None and module_name:
        base_dir = Path(__file__).parent.parent
        config_path = base_dir / module_name / "config.txt"
    elif config_path is None:
        logger.warning("No config path or module name provided")
        return defaults.copy() if defaults else {}

    return ConfigLoader.load(config_path, defaults, strict)
