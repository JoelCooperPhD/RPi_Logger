"""
Cross-platform file sync utilities.

Provides platform-independent functions for syncing file data to disk.
On POSIX systems (Linux, macOS), uses os.fsync().
On Windows, uses msvcrt._commit() which wraps FlushFileBuffers.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Union

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("FileSyncUtils")

# Platform-specific imports
_msvcrt = None
if sys.platform == "win32":
    try:
        import msvcrt as _msvcrt
    except ImportError:
        logger.debug("msvcrt not available - fsync will be no-op on Windows")


def safe_fsync(fd: int) -> bool:
    """Sync file descriptor to disk (cross-platform).

    On POSIX systems, calls os.fsync(fd).
    On Windows, calls msvcrt._commit(fd) which maps to FlushFileBuffers.

    Args:
        fd: Open file descriptor to sync.

    Returns:
        True if sync succeeded, False if it failed (silent failure).

    Note:
        This is "best effort" - failures are logged at debug level
        but do not raise exceptions. fsync is advisory on some systems.
    """
    try:
        if sys.platform == "win32":
            if _msvcrt is not None:
                _msvcrt._commit(fd)
            else:
                return False
        else:
            os.fsync(fd)
        return True
    except OSError as e:
        logger.debug("fsync failed for fd %d: %s", fd, e)
        return False


def fsync_path(path: Union[str, Path]) -> bool:
    """Open a file, sync it to disk, and close it (cross-platform).

    Useful for syncing files that are not currently open, such as
    video files written by external processes (ffmpeg).

    Args:
        path: Path to the file to sync.

    Returns:
        True if sync succeeded, False if it failed (silent failure).

    Note:
        Opens the file read-only to avoid modifying access times
        where possible.
    """
    try:
        path = Path(path)
        if sys.platform == "win32":
            flags = os.O_RDONLY | os.O_BINARY
        else:
            flags = os.O_RDONLY

        fd = os.open(str(path), flags)
        try:
            return safe_fsync(fd)
        finally:
            os.close(fd)
    except (OSError, FileNotFoundError) as e:
        logger.debug("fsync_path failed for %s: %s", path, e)
        return False


def fsync_file(file_obj) -> bool:
    """Sync an open file object to disk (cross-platform).

    Convenience wrapper that flushes the file buffer, extracts fileno()
    from a file object, and calls safe_fsync().

    Args:
        file_obj: Open file object with flush() and fileno() methods.

    Returns:
        True if sync succeeded, False if it failed (silent failure).
    """
    try:
        file_obj.flush()
        fd = file_obj.fileno()
        return safe_fsync(fd)
    except (OSError, AttributeError, ValueError) as e:
        logger.debug("fsync_file failed: %s", e)
        return False


__all__ = ["safe_fsync", "fsync_path", "fsync_file"]
