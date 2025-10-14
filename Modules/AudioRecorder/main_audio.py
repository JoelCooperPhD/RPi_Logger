#!/usr/bin/env python3
"""
Multi-microphone audio recording system with master-slave architecture.
Entry point for audio system with CLI argument parsing.
"""

import argparse
import asyncio
import contextlib
import logging
import os
import re
import signal
import sys
from pathlib import Path
from typing import Optional

# Import from parent modules - assumes proper PYTHONPATH or package installation
try:
    from cli_utils import (
        add_common_cli_arguments,
        configure_logging,
        ensure_directory,
        positive_int,
    )
except ImportError as e:
    print(f"ERROR: Cannot import cli_utils. Ensure PYTHONPATH includes project root or install package.", file=sys.stderr)
    print(f"  Add to PYTHONPATH: export PYTHONPATH=/home/rs-pi-2/Development/RPi_Logger:$PYTHONPATH", file=sys.stderr)
    print(f"  Or install package: cd /home/rs-pi-2/Development/RPi_Logger && pip install -e .", file=sys.stderr)
    sys.exit(1)

# Note: audio_core import is delayed until after stderr/stdout redirection
# This ensures clean output capture in the log file

logger = logging.getLogger("AudioMain")


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
        name = 'experiment'

    return name


def parse_args(argv: Optional[list[str]] = None):
    """Parse command line arguments with config file defaults."""
    # Load config file first (import here to avoid loading audio libraries early)
    from audio_core import load_config_file
    config = load_config_file()

    # Get defaults from config file or use hardcoded defaults
    def get_config_int(key, default):
        return int(config.get(key, default)) if key in config else default

    def get_config_float(key, default):
        return float(config.get(key, default)) if key in config else default

    def get_config_bool(key, default):
        if key in config:
            value = config[key]
            # If already a boolean (parsed by config loader), return it
            if isinstance(value, bool):
                return value
            # Otherwise parse from string
            return str(value).lower() in ('true', '1', 'yes', 'on')
        return default

    def get_config_str(key, default):
        return config.get(key, default)

    # Apply config defaults
    default_sample_rate = get_config_int('sample_rate', 48000)
    default_output = Path(get_config_str('output_dir', 'recordings'))
    default_session_prefix = get_config_str('session_prefix', 'experiment')
    default_auto_select_new = get_config_bool('auto_select_new', True)
    default_auto_start_recording = get_config_bool('auto_start_recording', False)
    default_console_output = get_config_bool('console_output', False)
    default_discovery_timeout = get_config_float('discovery_timeout', 5.0)
    default_discovery_retry = get_config_float('discovery_retry', 3.0)

    parser = argparse.ArgumentParser(description="Multi-microphone audio recorder")
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=("interactive", "slave", "headless"),
        default_mode="interactive",
    )

    parser.add_argument(
        "--sample-rate",
        type=positive_int,
        default=default_sample_rate,
        help="Sample rate (Hz) for each active microphone",
    )

    parser.add_argument(
        "--session-prefix",
        type=str,
        default=default_session_prefix,
        help="Prefix for experiment directories",
    )

    # Auto-select control
    auto_select_group = parser.add_mutually_exclusive_group()
    auto_select_group.add_argument(
        "--auto-select-new",
        dest="auto_select_new",
        action="store_true",
        default=default_auto_select_new,
        help="Automatically select newly detected input devices",
    )
    auto_select_group.add_argument(
        "--no-auto-select-new",
        dest="auto_select_new",
        action="store_false",
        help="Disable automatic selection of new devices",
    )

    # Recording control
    recording_group = parser.add_mutually_exclusive_group()
    recording_group.add_argument(
        "--auto-start-recording",
        dest="auto_start_recording",
        action="store_true",
        default=default_auto_start_recording,
        help="Automatically start recording on startup",
    )
    recording_group.add_argument(
        "--no-auto-start-recording",
        dest="auto_start_recording",
        action="store_false",
        help="Wait for manual recording command (default)",
    )

    # Logging control
    console_group = parser.add_mutually_exclusive_group()
    console_group.add_argument(
        "--console",
        dest="console_output",
        action="store_true",
        default=default_console_output,
        help="Also log to console (in addition to file)",
    )
    console_group.add_argument(
        "--no-console",
        dest="console_output",
        action="store_false",
        help="Log to file only (no console output)",
    )

    # Discovery settings
    parser.add_argument(
        "--discovery-timeout",
        type=positive_int,
        default=default_discovery_timeout,
        help="Device discovery timeout (seconds)",
    )
    parser.add_argument(
        "--discovery-retry",
        type=positive_int,
        default=default_discovery_retry,
        help="Device discovery retry interval (seconds)",
    )

    # Legacy compatibility flags
    parser.add_argument("--slave", dest="mode", action="store_const", const="slave", help=argparse.SUPPRESS)
    parser.add_argument("--headless", dest="mode", action="store_const", const="headless", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    return args


class AnsiStripWriter:
    """
    File wrapper that strips ANSI escape codes before writing.
    This cleans up colored output from libraries.
    Optimized to only run regex if ANSI codes are detected.
    """
    def __init__(self, file_obj):
        self.file = file_obj
        # ANSI escape sequence pattern
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def write(self, data):
        # Fast path: only strip if ANSI codes are present
        if '\x1B' in data:
            clean_data = self.ansi_escape.sub('', data)
            return self.file.write(clean_data)
        else:
            # No ANSI codes, write directly
            return self.file.write(data)

    def flush(self):
        return self.file.flush()

    def fileno(self):
        return self.file.fileno()


def redirect_stderr_stdout(log_file_path: Path):
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


async def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for audio recording system."""
    args = parse_args(argv)
    args.output_dir = ensure_directory(args.output_dir)

    # Create session directory for logging and recordings
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Sanitize session prefix to prevent path traversal attacks
    prefix = sanitize_path_component(args.session_prefix).rstrip("_")
    session_name = f"{prefix}_{timestamp}" if prefix else timestamp
    session_dir = args.output_dir / session_name

    # Validate that session_dir is actually within output_dir (prevent path traversal)
    try:
        session_dir_resolved = session_dir.resolve()
        output_dir_resolved = args.output_dir.resolve()
        if not str(session_dir_resolved).startswith(str(output_dir_resolved)):
            logger.error("Security violation: session directory escapes output directory")
            raise ValueError("Invalid session directory path")
    except (OSError, ValueError) as e:
        logger.error("Failed to validate session directory: %s", e)
        raise

    session_dir.mkdir(parents=True, exist_ok=True)

    # Configure logging to session directory
    log_file = session_dir / "session.log"

    # Redirect stderr/stdout to log file BEFORE configuring logging
    # This captures ALL output:
    # - Python logging
    # - C/C++ library output
    # ANSI color codes are automatically stripped
    # Returns original stdout for user-facing messages
    original_stdout = redirect_stderr_stdout(log_file)

    # Set StatusMessage output stream for slave mode BEFORE any imports that might use it
    if args.mode == "slave":
        from audio_core.commands import StatusMessage
        StatusMessage.output_stream = original_stdout

    # Now configure Python logging
    # If console_output is True, Python logging will ALSO write to console (via StreamHandler)
    configure_logging(args.log_level, str(log_file), console_output=args.console_output)

    # Store session_dir and console_stdout in args so AudioSystem can use them
    args.session_dir = session_dir
    args.console_stdout = original_stdout

    logger.info("=" * 60)
    logger.info("Audio System Starting")
    logger.info("=" * 60)
    logger.info("Session: %s", session_name)
    logger.info("Log file: %s", log_file)
    logger.info("Mode: %s", args.mode)
    logger.info("Sample rate: %d Hz", args.sample_rate)
    logger.info("Console output: %s", args.console_output)
    logger.info("=" * 60)

    # Import AudioSupervisor AFTER stderr/stdout redirection
    # This ensures library initialization output is captured in log file
    from audio_core import AudioSupervisor

    supervisor = AudioSupervisor(args)
    loop = asyncio.get_running_loop()

    # Track shutdown state to prevent race conditions
    shutdown_in_progress = False

    # Signal handler that properly schedules shutdown task
    def signal_handler():
        """Handle shutdown signals by scheduling shutdown task."""
        nonlocal shutdown_in_progress
        if not supervisor.shutdown_event.is_set() and not shutdown_in_progress:
            shutdown_in_progress = True
            asyncio.create_task(supervisor.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, signal_handler)

    try:
        await supervisor.run()
    finally:
        # Only shutdown if not already shutting down
        if not supervisor.shutdown_event.is_set():
            await supervisor.shutdown()
        logger.info("=" * 60)
        logger.info("Audio System Stopped")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
