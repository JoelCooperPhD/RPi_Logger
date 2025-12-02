"""VOG configuration loader."""

from pathlib import Path
from typing import Dict, Any

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base import ConfigLoader

logger = get_module_logger("VOGConfigLoader")

DEFAULTS = {
    "enabled": True,
    "visible": True,
    "display_name": "VOG",
    "window_x": 0,
    "window_y": 0,
    "window_width": 400,
    "window_height": 300,
    "window_geometry": "400x300",

    "device_vid": 0x16C0,
    "device_pid": 0x0483,
    "baudrate": 9600,

    "output_dir": "vog_data",
    "session_prefix": "vog",
    "log_level": "info",
    "console_output": False,

    "auto_start_recording": False,
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
