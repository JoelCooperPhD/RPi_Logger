from .constants import MODULE_NAME, MODULE_DESCRIPTION
from .gps_supervisor import GPSSupervisor

__all__ = ['MODULE_NAME', 'MODULE_DESCRIPTION', 'GPSSupervisor']


class GPSInitializationError(Exception):
    pass


def load_config_file():
    from pathlib import Path
    from logger_core.config_manager import get_config_manager

    config_path = Path(__file__).parent.parent / "config.txt"
    config_manager = get_config_manager()
    return config_manager.read_config(config_path)
