
import logging
from pathlib import Path
from typing import Dict, Any

from rpi_logger.modules.base import ConfigLoader as BaseConfigLoader

logger = logging.getLogger(__name__)


class ConfigLoader:

    @staticmethod
    def load(config_path: Path) -> Dict[str, Any]:
        return BaseConfigLoader.load(config_path, defaults=None)

    @staticmethod
    def _parse_value(value: str) -> Any:
        return BaseConfigLoader._parse_value(value)


def load_config_file(config_path: Path = None) -> Dict[str, Any]:
    if config_path is None:
        module_dir = Path(__file__).parent.parent.parent
        config_path = module_dir / "config.txt"

    return ConfigLoader.load(config_path)
