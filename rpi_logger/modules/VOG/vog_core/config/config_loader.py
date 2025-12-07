"""VOG configuration loader.

Device discovery is handled by the main logger - this module receives device assignments.
"""

from pathlib import Path
from typing import Dict, Any

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base import ConfigLoader

logger = get_module_logger("VOGConfigLoader")

DEFAULTS = {
    "enabled": True,
    "visible": True,
    "display_name": "VOG",
    "window_geometry": "400x300",
    "output_dir": "vog_data",
    "session_prefix": "vog",
    "log_level": "info",
    "console_output": False,
}


def load_config_file(config_path: Path = None) -> Dict[str, Any]:
    """Load VOG configuration from file with defaults.

    Args:
        config_path: Path to config file. If None, uses module's config.txt.

    Returns:
        Dict containing configuration values.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config.txt"

    logger.debug("Loading VOG config from: %s", config_path)
    return ConfigLoader.load(config_path, defaults=DEFAULTS, strict=False)
