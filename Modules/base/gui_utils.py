
import logging
import re
from pathlib import Path
from typing import Optional, Tuple

from rpi_logger.cli.common import get_config_int

logger = logging.getLogger(__name__)


def parse_geometry_string(geometry_str: str) -> Optional[Tuple[int, int, int, int]]:
    try:
        match = re.match(r'(\d+)x(\d+)([\+\-]\d+)([\+\-]\d+)', geometry_str)
        if not match:
            logger.error("Failed to parse geometry string: '%s'", geometry_str)
            return None

        width = int(match.group(1))
        height = int(match.group(2))
        x = int(match.group(3))  # Includes sign
        y = int(match.group(4))  # Includes sign

        return (width, height, x, y)

    except Exception as e:
        logger.error("Exception parsing geometry string '%s': %s", geometry_str, e)
        return None


def save_window_geometry(root_widget, config_path: Path) -> bool:
    logger.debug("Saving window geometry to config")

    try:
        from Modules.base import ConfigLoader

        geometry_str = root_widget.geometry()
        logger.debug("Current geometry string: '%s'", geometry_str)

        parsed = parse_geometry_string(geometry_str)
        if not parsed:
            return False

        width, height, x, y = parsed
        logger.debug("Parsed geometry: width=%d, height=%d, x=%d, y=%d", width, height, x, y)

        logger.debug("Config path: %s", config_path)
        if not config_path.exists():
            logger.error("Config file not found at: %s", config_path)
            return False

        updates = {
            'window_x': x,
            'window_y': y,
            'window_width': width,
            'window_height': height,
        }
        logger.debug("Calling ConfigLoader.update_config_values() with: %s", updates)

        result = ConfigLoader.update_config_values(config_path, updates)
        logger.debug("ConfigLoader.update_config_values() returned: %s", result)

        if result:
            logger.info("Saved window geometry: %dx%d+%d+%d", width, height, x, y)
        else:
            logger.error("ConfigLoader.update_config_values() returned False")

        return result

    except ImportError as e:
        logger.error("Failed to import ConfigLoader: %s", e, exc_info=True)
        return False
    except Exception as e:
        logger.error("Unexpected exception in save_window_geometry(): %s", e, exc_info=True)
        return False


def send_geometry_to_parent(root_widget) -> bool:
    try:
        logger.debug("Sending geometry to parent process")
        from logger_core.commands import StatusMessage

        geometry_str = root_widget.geometry()
        logger.debug("Current geometry string: %s", geometry_str)

        parsed = parse_geometry_string(geometry_str)
        if not parsed:
            logger.error("Failed to parse geometry: '%s'", geometry_str)
            return False

        width, height, x, y = parsed
        logger.debug("Parsed values: width=%d, height=%d, x=%d, y=%d", width, height, x, y)

        payload = {
            "width": width,
            "height": height,
            "x": x,
            "y": y
        }
        logger.debug("Sending StatusMessage with payload: %s", payload)
        StatusMessage.send("geometry_changed", payload)
        logger.info("Sent geometry to parent: %dx%d+%d+%d", width, height, x, y)
        return True

    except ImportError as e:
        logger.debug("StatusMessage not available (standalone mode): %s", e)
        return False
    except Exception as e:
        logger.error("Failed to send geometry to parent: %s", e, exc_info=True)
        return False


def get_module_config_path(gui_file_path: Path) -> Path:
    module_dir = gui_file_path.parent.parent.parent.parent
    return module_dir / "config.txt"


def load_window_geometry_from_config(config: dict, current_geometry: Optional[str] = None) -> Optional[str]:
    if current_geometry:
        logger.debug("Using command-line window geometry (overriding config): %s", current_geometry)
        return current_geometry

    logger.debug("Loading window geometry from config")

    try:
        if 'window_geometry' in config:
            geometry_str = config['window_geometry']
            if geometry_str and isinstance(geometry_str, str):
                logger.debug("Loaded window geometry from config (new format): %s", geometry_str)
                return geometry_str

        window_x = get_config_int(config, 'window_x', None)
        window_y = get_config_int(config, 'window_y', None)
        window_width = get_config_int(config, 'window_width', None)
        window_height = get_config_int(config, 'window_height', None)

        if all(v is not None for v in [window_x, window_y, window_width, window_height]):
            geometry_str = f"{window_width}x{window_height}+{window_x}+{window_y}"
            logger.debug("Loaded window geometry from config (old format): %s", geometry_str)
            return geometry_str
        else:
            logger.debug("Window geometry not fully specified in config")
            return None

    except ImportError as e:
        logger.error("Failed to import get_config_int: %s", e)
        return None
    except Exception as e:
        logger.error("Failed to load window geometry from config: %s", e)
        return None
