#!/usr/bin/env python3
"""
Session Utilities - Session directory management for all modules.

Provides common functionality for:
- Session directory creation
- Session naming
- Command mode detection
- Path validation
"""

import datetime
import logging
import sys
from pathlib import Path
from typing import Optional, Tuple

from .io_utils import sanitize_path_component

logger = logging.getLogger(__name__)


def detect_command_mode(args) -> bool:
    """
    Detect if module is running in command mode (controlled by master logger).

    Command mode is detected when:
    - Mode is explicitly set to 'slave'
    - stdin is not a TTY (piped from parent process)
    - --enable-commands flag is set

    Args:
        args: Parsed command line arguments

    Returns:
        True if running in command mode, False for standalone mode
    """
    # Check explicit slave mode
    mode = getattr(args, 'mode', None)
    if mode == 'slave':
        return True

    # Check if --enable-commands flag is set
    if getattr(args, 'enable_commands', False):
        return True

    # Check if stdin is piped (not a TTY)
    if not sys.stdin.isatty():
        return True

    return False


def create_session_directory(
    output_dir: Path,
    session_prefix: str = 'session',
    is_command_mode: bool = False,
    module_name: Optional[str] = None
) -> Tuple[Path, str, Path]:
    """
    Create session directory based on mode.

    In command mode: Uses output_dir directly (master logger already created it)
    In standalone mode: Creates timestamped subdirectory

    Args:
        output_dir: Base output directory
        session_prefix: Prefix for session directory name
        is_command_mode: Whether running in command mode
        module_name: Module name for log file naming (e.g., 'audio', 'camera')

    Returns:
        Tuple of (session_dir, session_name, log_file_path)
    """
    if is_command_mode:
        # Command mode: Use output_dir directly (no nested session)
        # Master logger already created the module subdirectory
        session_dir = output_dir
        session_name = session_dir.name  # Use directory name as session name

        # Module-specific log name
        if module_name:
            log_file = session_dir / f"{module_name}.log"
        else:
            log_file = session_dir / "module.log"

    else:
        # Standalone mode: Create timestamped session directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # Sanitize session prefix to prevent path traversal attacks
        prefix = sanitize_path_component(session_prefix).rstrip("_")
        session_name = f"{prefix}_{timestamp}" if prefix else timestamp
        session_dir = output_dir / session_name

        # Validate that session_dir is actually within output_dir (prevent path traversal)
        try:
            session_dir_resolved = session_dir.resolve()
            output_dir_resolved = output_dir.resolve()
            if not str(session_dir_resolved).startswith(str(output_dir_resolved)):
                logger.error("Security violation: session directory escapes output directory")
                raise ValueError("Invalid session directory path")
        except (OSError, ValueError) as e:
            logger.error("Failed to validate session directory: %s", e)
            raise

        session_dir.mkdir(parents=True, exist_ok=True)
        log_file = session_dir / "session.log"  # Generic log name for standalone

    return session_dir, session_name, log_file


def setup_session_from_args(
    args,
    module_name: Optional[str] = None,
    default_prefix: str = 'session'
) -> Tuple[Path, str, Path, bool]:
    """
    Setup session directory from command line arguments.

    This is a convenience function that combines command mode detection
    and session directory creation.

    Args:
        args: Parsed command line arguments (must have output_dir attribute)
        module_name: Module name for log file naming (e.g., 'audio', 'camera')
        default_prefix: Default session prefix if not in args

    Returns:
        Tuple of (session_dir, session_name, log_file, is_command_mode)
    """
    # Detect command mode
    is_command_mode = detect_command_mode(args)

    # Get session prefix from args or use default
    session_prefix = getattr(args, 'session_prefix', default_prefix)

    # Create session directory
    session_dir, session_name, log_file = create_session_directory(
        output_dir=args.output_dir,
        session_prefix=session_prefix,
        is_command_mode=is_command_mode,
        module_name=module_name
    )

    return session_dir, session_name, log_file, is_command_mode
