#!/usr/bin/env python3
"""
Eye tracking system with master-slave architecture.
Entry point for tracker system with CLI argument parsing.
"""

import argparse
import asyncio
import contextlib
import datetime
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
        parse_resolution,
        positive_float,
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

logger = logging.getLogger("TrackerMain")


def parse_args(argv: Optional[list[str]] = None):
    """Parse command line arguments with config file defaults."""
    # Load config file first
    from tracker_core import load_config_file
    config = load_config_file()

    # Apply config defaults
    default_width = get_config_int(config, 'resolution_width', 1280)
    default_height = get_config_int(config, 'resolution_height', 720)
    default_resolution = (default_width, default_height)
    default_fps = get_config_float(config, 'target_fps', 5.0)
    default_output = Path(get_config_str(config, 'output_dir', 'recordings'))
    default_session_prefix = get_config_str(config, 'session_prefix', 'tracking')
    default_preview_width = get_config_int(config, 'preview_width', 640)
    default_auto_start_recording = get_config_bool(config, 'auto_start_recording', False)
    default_console_output = get_config_bool(config, 'console_output', False)
    default_discovery_timeout = get_config_float(config, 'discovery_timeout', 5.0)
    default_discovery_retry = get_config_float(config, 'discovery_retry', 3.0)
    default_gui_start_minimized = get_config_bool(config, 'gui_start_minimized', True)
    default_gui_preview_update_hz = get_config_int(config, 'gui_preview_update_hz', 10)

    parser = argparse.ArgumentParser(description="Eye tracking system with Pupil Labs integration")
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=("gui", "headless"),
        default_mode="gui",
    )

    parser.add_argument(
        "--target-fps",
        dest="target_fps",
        type=positive_float,
        default=default_fps,
        help="Target processing FPS (1-120)",
    )

    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=default_resolution,
        help="Scene video resolution (WIDTHxHEIGHT)",
    )

    parser.add_argument(
        "--preview-width",
        type=positive_int,
        default=default_preview_width,
        help="Preview window width in pixels",
    )

    parser.add_argument(
        "--session-prefix",
        type=str,
        default=default_session_prefix,
        help="Prefix for generated recording sessions",
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
        type=positive_float,
        default=default_discovery_timeout,
        help="Device discovery timeout (seconds)",
    )
    parser.add_argument(
        "--discovery-retry",
        type=positive_float,
        default=default_discovery_retry,
        help="Device discovery retry interval (seconds)",
    )

    # GUI startup size control
    gui_size_group = parser.add_mutually_exclusive_group()
    gui_size_group.add_argument(
        "--gui-minimized",
        dest="gui_start_minimized",
        action="store_true",
        default=default_gui_start_minimized,
        help="Start GUI with minimal window size (default from config)",
    )
    gui_size_group.add_argument(
        "--gui-fullsize",
        dest="gui_start_minimized",
        action="store_false",
        help="Start GUI at capture resolution",
    )

    # GUI update rates
    parser.add_argument(
        "--gui-preview-update-hz",
        dest="gui_preview_update_hz",
        type=positive_int,
        default=default_gui_preview_update_hz,
        help="GUI preview update rate in Hz (1-30)",
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
    parser.add_argument("--tkinter", dest="mode", action="store_const", const="gui", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    args.width, args.height = args.resolution

    return args


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    args.output_dir = ensure_directory(args.output_dir)

    # Setup session directory and logging using shared utilities
    session_dir, session_name, log_file, is_command_mode = setup_session_from_args(
        args,
        module_name='eyetracker',
        default_prefix='tracking'
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
    configure_logging(args.log_level, str(log_file), console_output=args.console_output)

    # Store session_dir and stdout streams in args so TrackerSystem can use them
    args.session_dir = session_dir
    args.console_stdout = original_stdout  # For console messages
    args.command_stdout = original_stdout  # For parent process communication

    logger.info("=" * 60)
    logger.info("Eye Tracker System Starting")
    logger.info("=" * 60)
    logger.info("Session: %s", session_name)
    logger.info("Log file: %s", log_file)
    logger.info("Mode: %s", args.mode)
    logger.info("Target FPS: %.1f", args.target_fps)
    logger.info("Resolution: %dx%d", args.width, args.height)
    logger.info("Console output: %s", args.console_output)
    logger.info("=" * 60)

    # Import TrackerSupervisor AFTER stderr/stdout redirection
    from tracker_core import TrackerSupervisor

    supervisor = TrackerSupervisor(args)
    loop = asyncio.get_running_loop()

    # Signal handler that properly schedules shutdown task
    def signal_handler():
        """Handle shutdown signals by scheduling shutdown task."""
        if not supervisor.shutdown_event.is_set():
            asyncio.create_task(supervisor.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, signal_handler)

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()
        logger.info("=" * 60)
        logger.info("Eye Tracker System Stopped")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
