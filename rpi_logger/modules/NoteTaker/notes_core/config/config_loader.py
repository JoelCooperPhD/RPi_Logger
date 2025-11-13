
import logging
from pathlib import Path
from typing import Dict, Any

from rpi_logger.modules.base import ConfigLoader

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": False,
    "window_x": 0,
    "window_y": 0,
    "window_width": 600,
    "window_height": 500,

    "output_dir": "notes",
    "session_prefix": "notes",
    "log_level": "info",
    "console_output": False,

    "auto_start_recording": False,

    "gui_show_note_history": True,
    "max_displayed_notes": 100,
}


def load_config_file(config_path: Path = None) -> Dict[str, Any]:
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config.txt"

    logger.debug("Loading NoteTaker config from: %s", config_path)
    return ConfigLoader.load(config_path, defaults=DEFAULTS, strict=False)
