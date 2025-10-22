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
        get_config_int,
        get_config_float,
        get_config_bool,
        get_config_str,
    )
    from Modules.base import redirect_stderr_stdout, setup_session_from_args
except ImportError as e:
    print(f"ERROR: Cannot import required modules. Ensure PYTHONPATH includes project root or install package.", file=sys.stderr)
    print(f"  Add to PYTHONPATH: export PYTHONPATH=/home/rs-pi-2/Development/RPi_Logger:$PYTHONPATH", file=sys.stderr)
    print(f"  Or install package: cd /home/rs-pi-2/Development/RPi_Logger && pip install -e .", file=sys.stderr)
    sys.exit(1)

# Note: audio_core import is delayed until after stderr/stdout redirection
# This ensures clean output capture in the log file

logger = logging.getLogger("AudioMain")


def parse_args(argv: Optional[list[str]] = None):
    """Parse command line arguments with config file defaults."""
    # Load config file first (import here to avoid loading audio libraries early)
    from audio_core import load_config_file
    config = load_config_file()

    # Apply config defaults
    default_sample_rate = get_config_int(config, 'sample_rate', 48000)
    default_output = Path(get_config_str(config, 'output_dir', 'recordings'))
    default_session_prefix = get_config_str(config, 'session_prefix', 'experiment')
    default_auto_select_new = get_config_bool(config, 'auto_select_new', True)
    default_auto_start_recording = get_config_bool(config, 'auto_start_recording', False)
    default_console_output = get_config_bool(config, 'console_output', False)
    default_discovery_timeout = get_config_float(config, 'discovery_timeout', 5.0)
    default_discovery_retry = get_config_float(config, 'discovery_retry', 3.0)

    # Window geometry defaults (for GUI mode)
    default_window_x = get_config_int(config, 'window_x', None)
    default_window_y = get_config_int(config, 'window_y', None)
    default_window_width = get_config_int(config, 'window_width', None)
    default_window_height = get_config_int(config, 'window_height', None)

    parser = argparse.ArgumentParser(description="Multi-microphone audio recorder")
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=("gui", "headless"),
        default_mode="gui",
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

    # Parent process communication control
    parser.add_argument(
        "--enable-commands",
        dest="enable_commands",
        action="store_true",
        default=False,
        help="Enable JSON command interface for parent process control (auto-detected if stdin is piped)",
    )

    # Window geometry control (for GUI mode)
    parser.add_argument(
        "--window-geometry",
        dest="window_geometry",
        type=str,
        default=None,
        help="Window position and size (format: WIDTHxHEIGHT+X+Y, e.g., 800x600+100+50)",
    )

    # Legacy compatibility flags (hidden from help)
    parser.add_argument("--slave", dest="mode", action="store_const", const="slave", help=argparse.SUPPRESS)
    parser.add_argument("--headless", dest="mode", action="store_const", const="headless", help=argparse.SUPPRESS)
    parser.add_argument("--interactive", dest="mode", action="store_const", const="gui", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    # Apply window geometry from config if not provided via --window-geometry
    # and if all geometry values are present in config
    if not args.window_geometry:
        if all(v is not None for v in [default_window_x, default_window_y,
                                       default_window_width, default_window_height]):
            args.window_geometry = f"{default_window_width}x{default_window_height}+{default_window_x}+{default_window_y}"

    return args


async def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for audio recording system."""
    args = parse_args(argv)
    args.output_dir = ensure_directory(args.output_dir)

    # Setup session directory and logging using shared utilities
    session_dir, session_name, log_file, is_command_mode = setup_session_from_args(
        args,
        module_name='audio',
        default_prefix='experiment'
    )

    # Redirect stderr/stdout to log file BEFORE configuring logging
    # Returns original stdout for user-facing messages and parent process communication
    original_stdout = redirect_stderr_stdout(log_file)

    # Configure StatusMessage to use original stdout if in command mode
    # This must be done BEFORE any imports that might send status messages
    if is_command_mode:
        from logger_core.commands import StatusMessage
        StatusMessage.configure(original_stdout)

    # Now configure Python logging
    # If console_output is True, Python logging will ALSO write to console (via StreamHandler)
    configure_logging(args.log_level, str(log_file), console_output=args.console_output)

    # Install global exception hooks to catch and log any unhandled exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        """Global exception handler to log uncaught exceptions."""
        if issubclass(exc_type, KeyboardInterrupt):
            # Call default handler for KeyboardInterrupt
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_exception

    # Store session_dir and stdout streams in args so AudioSystem can use them
    args.session_dir = session_dir
    args.console_stdout = original_stdout  # For console messages
    args.command_stdout = original_stdout  # For parent process communication

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

    # Install asyncio exception handler
    def handle_asyncio_exception(loop, context):
        """Handle exceptions from asyncio tasks."""
        exception = context.get('exception')
        message = context.get('message', 'Unhandled asyncio exception')
        if exception:
            logger.exception(f"Asyncio exception: {message}", exc_info=exception)
        else:
            logger.error(f"Asyncio error: {message}, context: {context}")

    loop.set_exception_handler(handle_asyncio_exception)

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
    except Exception as e:
        logger.exception("Unhandled exception in main: %s", e)
        raise  # Re-raise to preserve exit code
    finally:
        # Only shutdown if not already shutting down
        if not supervisor.shutdown_event.is_set():
            await supervisor.shutdown()
        logger.info("=" * 60)
        logger.info("Audio System Stopped")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
