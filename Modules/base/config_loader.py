
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ConfigLoader:

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

        if target_type in (int, float):
            try:
                return target_type(value)
            except ValueError:
                logger.warning("Failed to parse '%s' as %s, using default", value, target_type.__name__)
                return target_type()  # Return 0 or 0.0

        return value

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
                        value = updates[key]

                        if isinstance(value, bool):
                            value_str = 'true' if value else 'false'
                        else:
                            value_str = str(value)

                        if '#' in stripped.split('=', 1)[1]:
                            comment = '#' + stripped.split('#', 1)[1]
                            lines[i] = f"{' ' * indent}{key} = {value_str} {comment}\n"
                        else:
                            lines[i] = f"{' ' * indent}{key} = {value_str}\n"

                        updated_keys.add(key)

            with open(config_path, 'w') as f:
                f.writelines(lines)

            logger.info("Updated config file: %s (keys: %s)", config_path, updated_keys)
            return True

        except Exception as e:
            logger.error("Failed to update config file: %s", e, exc_info=True)
            return False


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
