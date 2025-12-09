"""GPS module configuration loader."""

from pathlib import Path
from typing import Dict, Any

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base import ConfigLoader

logger = get_module_logger("GPSConfigLoader")

DEFAULTS = {
    # Module settings
    "enabled": True,
    "display_name": "GPS",

    # Window geometry
    "window_x": 0,
    "window_y": 0,
    "window_width": 900,
    "window_height": 700,

    # Serial configuration (port assigned by logger, not configured here)
    "baud_rate": 9600,
    "reconnect_delay_s": 3.0,

    # NMEA settings
    "nmea_history": 30,

    # Map settings
    "offline_db": "offline_tiles.db",
    "center_lat": 40.7608,
    "center_lon": -111.8910,
    "zoom": 13,

    # Display preferences
    "speed_unit": "km/h",  # km/h, mph, knots, m/s
    "altitude_unit": "meters",  # meters, feet

    # Output
    "output_dir": "gps_data",
    "session_prefix": "gps",
    "log_level": "info",
    "console_output": False,

    # UI visibility
    "gui_io_stub_visible": False,
    "gui_logger_visible": False,
    "view.show_io_panel": False,
    "view.show_logger": True,
}


def load_config_file(config_path: Path = None) -> Dict[str, Any]:
    """Load GPS configuration with defaults.

    Args:
        config_path: Path to config.txt file. If None, uses default location.

    Returns:
        Configuration dictionary with defaults applied.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config.txt"

    logger.debug("Loading GPS config from: %s", config_path)
    return ConfigLoader.load(config_path, defaults=DEFAULTS, strict=False)
