"""VOG configuration loader.

Supports both sVOG (wired) and wVOG (wireless) devices.
The system monitors for both device types regardless of which is specified in config.
"""

from pathlib import Path
from typing import Dict, Any

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base import ConfigLoader

from ..constants import (
    SVOG_VID, SVOG_PID, SVOG_BAUD,
    WVOG_VID, WVOG_PID, WVOG_BAUD,
    WVOG_DONGLE_VID, WVOG_DONGLE_PID, WVOG_DONGLE_BAUD,
)

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

    # Primary device settings (system monitors both types)
    "device_vid": SVOG_VID,
    "device_pid": SVOG_PID,
    "baudrate": SVOG_BAUD,

    # sVOG-specific settings (Arduino-based, 115200 baud)
    "svog_vid": SVOG_VID,
    "svog_pid": SVOG_PID,
    "svog_baud": SVOG_BAUD,  # 115200

    # wVOG-specific settings
    "wvog_vid": WVOG_VID,
    "wvog_pid": WVOG_PID,
    "wvog_baud": WVOG_BAUD,

    # wVOG dongle (XBee host) settings
    "dongle_vid": WVOG_DONGLE_VID,
    "dongle_pid": WVOG_DONGLE_PID,
    "dongle_baud": WVOG_DONGLE_BAUD,

    # XBee settings for wVOG wireless mode
    "xbee_discovery_timeout": 10,
    "xbee_retry_count": 3,

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
