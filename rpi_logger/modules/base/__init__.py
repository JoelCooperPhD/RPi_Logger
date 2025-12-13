"""
Base module utilities for Logger modules.

This module provides shared utilities and base classes for module development.

For new modules, use:
    from vmc import ModuleRuntime, RuntimeContext, StubCodexSupervisor

See stub (codex)/vmc/ for the VMC framework implementation.
"""

from .base_supervisor import BaseSupervisor
from .config_loader import ConfigLoader, load_config_file
from .task_manager import AsyncTaskManager
from .recording_mixin import RecordingStateMixin
from .async_utils import (
    save_file_async,
    gather_with_logging,
    gather_with_timeout,
    run_with_retries,
    cancel_task_safely,
)
from .io_utils import (
    AnsiStripWriter,
    redirect_stderr_stdout,
    sanitize_path_component,
    sanitize_error_message,
)
from .config_paths import (
    ModuleConfigContext,
    resolve_module_config_path,
    resolve_writable_module_config,
)
from .preferences import ModulePreferences, PreferenceChange, ScopedPreferences, StatePersistence
from .session_utils import (
    detect_command_mode,
    create_session_directory,
    setup_session_from_args,
)
from .utils import RollingFPS
from .gui_utils import (
    parse_geometry_string,
    send_geometry_to_parent,
)
from .tkinter_gui_base import TkinterGUIBase
from .tkinter_menu_base import TkinterMenuBase
from .metadata import (
    DeviceType,
    FrameMetadata,
    GazeMetadata,
    CameraMetadata,
)
from .recording import RecordingManagerBase
from .status import (
    ModuleState,
    StatusType,
    ModuleStatus,
    create_ready_status,
    create_error_status,
    create_recording_started_status,
    create_recording_stopped_status,
)

__all__ = [
    'BaseSupervisor',
    'RecordingStateMixin',
    'AsyncTaskManager',
    'save_file_async',
    'gather_with_logging',
    'gather_with_timeout',
    'run_with_retries',
    'cancel_task_safely',
    'ConfigLoader',
    'load_config_file',
    'AnsiStripWriter',
    'redirect_stderr_stdout',
    'sanitize_path_component',
    'sanitize_error_message',
    'ModuleConfigContext',
    'resolve_module_config_path',
    'resolve_writable_module_config',
    'ModulePreferences',
    'PreferenceChange',
    'ScopedPreferences',
    'StatePersistence',
    'detect_command_mode',
    'create_session_directory',
    'setup_session_from_args',
    'RollingFPS',
    'parse_geometry_string',
    'send_geometry_to_parent',
    'TkinterGUIBase',
    'TkinterMenuBase',
    # Phase 2: Cross-module standardization
    'DeviceType',
    'FrameMetadata',
    'GazeMetadata',
    'CameraMetadata',
    'RecordingManagerBase',
    'ModuleState',
    'StatusType',
    'ModuleStatus',
    'create_ready_status',
    'create_error_status',
    'create_recording_started_status',
    'create_recording_stopped_status',
]
