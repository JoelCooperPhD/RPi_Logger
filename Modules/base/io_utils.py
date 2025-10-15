#!/usr/bin/env python3
"""
IO Utilities - Shared I/O helpers for all modules.

Provides common functionality for:
- ANSI escape code stripping
- Stream redirection
- Path sanitization
- Error message sanitization
"""

import os
import re
import sys
from pathlib import Path
from typing import TextIO, Union


class AnsiStripWriter:
    """
    File wrapper that strips ANSI escape codes before writing.

    This cleans up colored output from libraries.
    Optimized to only run regex if ANSI codes are detected.
    """

    def __init__(self, file_obj: TextIO):
        """
        Initialize ANSI stripper.

        Args:
            file_obj: File object to write to
        """
        self.file = file_obj
        # ANSI escape sequence pattern
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def write(self, data: str) -> int:
        """
        Write data to file, stripping ANSI codes if present.

        Args:
            data: String data to write

        Returns:
            Number of characters written
        """
        # Fast path: only strip if ANSI codes are present
        if '\x1B' in data:
            clean_data = self.ansi_escape.sub('', data)
            return self.file.write(clean_data)
        else:
            # No ANSI codes, write directly
            return self.file.write(data)

    def flush(self) -> None:
        """Flush the underlying file."""
        return self.file.flush()

    def fileno(self) -> int:
        """Get file descriptor."""
        return self.file.fileno()


def sanitize_path_component(name: str) -> str:
    """
    Sanitize a path component to prevent directory traversal attacks.

    Removes or replaces dangerous characters like '/', '\\', '..', etc.

    Args:
        name: Path component to sanitize

    Returns:
        Sanitized path component safe for use in file paths
    """
    # Remove null bytes
    name = name.replace('\0', '')

    # Remove path separators and parent directory references
    # Replace with underscores to maintain readability
    name = name.replace('/', '_').replace('\\', '_')
    name = name.replace('..', '__')

    # Remove other potentially dangerous characters
    # Keep only alphanumeric, dash, underscore, and dot
    name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', name)

    # Ensure it doesn't start with a dot (hidden file)
    if name.startswith('.'):
        name = '_' + name[1:]

    # Ensure non-empty
    if not name or name.isspace():
        name = 'default'

    return name


def redirect_stderr_stdout(log_file_path: Path) -> TextIO:
    """
    Redirect stderr and stdout to log file at the OS level.

    This captures ALL output including:
    - Python logging
    - Python print() statements
    - C/C++ library output

    ANSI color codes are stripped for clean log output.

    Note: This function uses synchronous file operations as it must be called
    before the asyncio event loop starts. The file remains open for the session.

    Args:
        log_file_path: Path to log file

    Returns:
        Original stdout file object for user-facing messages
    """
    # Preserve original stdout for user-facing messages
    # We need to duplicate the file descriptor before redirecting
    original_stdout_fd = os.dup(sys.stdout.fileno())
    original_stdout = os.fdopen(original_stdout_fd, 'w', buffering=1)

    # Open log file in append mode (synchronous - required before event loop)
    log_file = open(log_file_path, 'a', buffering=1)

    # Wrap with ANSI stripper
    clean_log = AnsiStripWriter(log_file)

    # Get file descriptor from underlying file
    log_fd = log_file.fileno()

    # Redirect stderr and stdout file descriptors to log file
    # This captures everything, including C library output
    os.dup2(log_fd, sys.stderr.fileno())
    os.dup2(log_fd, sys.stdout.fileno())

    # Replace Python's stderr/stdout with ANSI-stripping wrappers
    sys.stderr = clean_log
    sys.stdout = clean_log

    return original_stdout


def sanitize_error_message(
    error: Union[Exception, str],
    max_length: int = 200
) -> str:
    """
    Sanitize error message to prevent information leakage.

    Removes file paths and other sensitive information from error messages
    before sending to external systems (e.g., master in slave mode, logs).

    Args:
        error: Exception or error message string to sanitize
        max_length: Maximum length of sanitized message

    Returns:
        Sanitized error message safe to send externally

    Examples:
        >>> sanitize_error_message(FileNotFoundError("/home/user/secret/file.txt not found"))
        "[path] not found"
        >>> sanitize_error_message("Error in /usr/local/bin/app")
        "Error in [path]"
    """
    msg = str(error)

    # Remove absolute paths (anything starting with / or drive letter on Windows)
    msg = re.sub(r'/[^\s]*', '[path]', msg)
    msg = re.sub(r'[A-Z]:\\[^\s]*', '[path]', msg)

    # Remove relative paths (../ or ./)
    msg = re.sub(r'\.\.?/[^\s]*', '[path]', msg)

    # Truncate long messages
    if len(msg) > max_length:
        msg = msg[:max_length - 3] + '...'

    return msg
