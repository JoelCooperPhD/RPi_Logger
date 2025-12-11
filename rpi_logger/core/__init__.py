
from .logger_system import LoggerSystem
from .module_discovery import discover_modules, ModuleInfo
from .module_process import ModuleProcess
from .module_state_manager import (
    ModuleStateManager,
    DesiredState,
    ActualState,
    StateEvent,
    StateChange,
    RUNNING_STATES,
    STOPPED_STATES,
)
from .shutdown_coordinator import get_shutdown_coordinator, ShutdownCoordinator
from .state_facade import StateFacade

__version__ = "2.0.0"

__all__ = [
    'LoggerSystem',
    'discover_modules',
    'ModuleInfo',
    'ModuleProcess',
    'ModuleStateManager',
    'DesiredState',
    'ActualState',
    'StateEvent',
    'StateChange',
    'RUNNING_STATES',
    'STOPPED_STATES',
    'get_shutdown_coordinator',
    'ShutdownCoordinator',
    'StateFacade',
    '__version__',
]
