
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from Modules.base import ConfigLoader as BaseConfigLoader

logger = logging.getLogger("ConfigLoader")


class ConfigLoader:

    @staticmethod
    def load_config(config_path: Path) -> Dict[str, Any]:
        return BaseConfigLoader.load(config_path, defaults=None)

    @staticmethod
    def _parse_value(value: str) -> Any:
        return BaseConfigLoader._parse_value(value)


def load_config_file(config_path: Optional[Path] = None) -> Dict[str, Any]:
    if config_path is None:
        module_dir = Path(__file__).parent.parent.parent
        config_path = module_dir / "config.txt"

    return ConfigLoader.load_config(config_path)
