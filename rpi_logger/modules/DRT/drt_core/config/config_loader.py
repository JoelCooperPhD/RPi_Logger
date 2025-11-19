import logging
from pathlib import Path
from typing import Dict, Any

from rpi_logger.modules.base import ConfigLoader

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": False,
    "window_x": 0,
    "window_y": 0,
    "window_width": 800,
    "window_height": 600,

    "device_vid": 0x239A,
    "device_pid": 0x801E,
    "baudrate": 9600,

    "output_dir": "drt_data",
    "session_prefix": "drt",
    "log_level": "info",
    "console_output": False,

    "auto_start_recording": False,

    "gui_show_session_output": True,
}


def load_config_file(config_path: Path = None) -> Dict[str, Any]:
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config.txt"

    logger.debug("Loading DRT config from: %s", config_path)
    return ConfigLoader.load(config_path, defaults=DEFAULTS, strict=False)
