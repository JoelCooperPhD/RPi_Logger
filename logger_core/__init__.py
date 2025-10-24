
from .logger_system import LoggerSystem
from .module_discovery import discover_modules, ModuleInfo
from .module_process import ModuleProcess
from .shutdown_coordinator import get_shutdown_coordinator, ShutdownCoordinator

__version__ = "1.0.0"

__all__ = [
    'LoggerSystem',
    'discover_modules',
    'ModuleInfo',
    'ModuleProcess',
    'get_shutdown_coordinator',
    'ShutdownCoordinator',
    '__version__',
]
