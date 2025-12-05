"""
Observer implementations for the module state manager.

These observers react to state changes and perform various side effects:
- ConfigPersistenceObserver: Persists enabled state to config files
- SessionRecoveryObserver: Manages running_modules.json for crash recovery
- UIStateObserver: Updates UI elements to reflect state changes
"""

from .config_persistence import ConfigPersistenceObserver
from .session_recovery import SessionRecoveryObserver
from .ui_state import UIStateObserver

__all__ = [
    'ConfigPersistenceObserver',
    'SessionRecoveryObserver',
    'UIStateObserver',
]
