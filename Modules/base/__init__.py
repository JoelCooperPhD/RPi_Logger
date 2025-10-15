"""
Module Base Package

Shared base classes and utilities for implementing modules.
Provides common patterns for supervisors, systems, modes, and utilities.
"""

from .base_supervisor import BaseSupervisor
from .base_system import BaseSystem
from .io_utils import (
    AnsiStripWriter,
    redirect_stderr_stdout,
    sanitize_path_component,
    sanitize_error_message,
)
from .session_utils import (
    detect_command_mode,
    create_session_directory,
    setup_session_from_args,
)
from .utils import RollingFPS

__all__ = [
    'BaseSupervisor',
    'BaseSystem',
    'AnsiStripWriter',
    'redirect_stderr_stdout',
    'sanitize_path_component',
    'sanitize_error_message',
    'detect_command_mode',
    'create_session_directory',
    'setup_session_from_args',
    'RollingFPS',
]
