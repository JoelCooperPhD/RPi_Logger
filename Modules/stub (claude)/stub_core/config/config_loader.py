import asyncio
import logging
from pathlib import Path
from typing import Dict, Any

from Modules.base import ConfigLoader

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": False,
    "window_geometry": "700x600+100+100",
}


async def load_config_file_async(config_path: Path = None) -> Dict[str, Any]:
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config.txt"

    logger.debug("Loading stub config from: %s", config_path)
    config = await ConfigLoader.load_async(config_path, defaults=DEFAULTS, strict=False)

    if "window_geometry" not in config and "window_width" in config:
        try:
            x = config.get("window_x", 100)
            y = config.get("window_y", 100)
            w = config.get("window_width", 700)
            h = config.get("window_height", 600)
            config["window_geometry"] = f"{w}x{h}+{x}+{y}"
            logger.debug("Migrated old geometry format to new format")
        except Exception as e:
            logger.warning(f"Failed to migrate geometry format: {e}")

    return config


def load_config_file(config_path: Path = None) -> Dict[str, Any]:
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config.txt"

    logger.debug("Loading stub config from: %s", config_path)
    config = ConfigLoader.load(config_path, defaults=DEFAULTS, strict=False)

    if "window_geometry" not in config and "window_width" in config:
        try:
            x = config.get("window_x", 100)
            y = config.get("window_y", 100)
            w = config.get("window_width", 700)
            h = config.get("window_height", 600)
            config["window_geometry"] = f"{w}x{h}+{x}+{y}"
            logger.debug("Migrated old geometry format to new format")
        except Exception as e:
            logger.warning(f"Failed to migrate geometry format: {e}")

    return config
