#!/usr/bin/env python3
"""
Multi-camera recording system with master-slave architecture.
Entry point for camera system with CLI argument parsing.
"""

import argparse
import asyncio
import contextlib
import logging
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
# Note: camera_core import is delayed until after stderr/stdout redirection
# This ensures libcamera output is captured in the log file

logger = logging.getLogger("CameraMain")


def parse_args(argv: Optional[list[str]] = None):
    # Load config file first (import here to avoid loading picamera2 early)
    from camera_core import load_config_file
    config = load_config_file()

    # Apply config defaults
    # Handle resolution preset from config (must be number 0-7)
    from cli_utils import parse_resolution as parse_res_helper
    resolution_preset_str = get_config_str(config, 'resolution_preset', '0')
    default_resolution = parse_res_helper(resolution_preset_str)

    preview_preset_str = get_config_str(config, 'preview_preset', '6')
    default_preview = parse_res_helper(preview_preset_str)
    default_fps = get_config_float(config, 'target_fps', 30.0)
    default_output = Path(get_config_str(config, 'output_dir', 'recordings'))
    default_session_prefix = get_config_str(config, 'session_prefix', 'session')
    default_show_preview = get_config_bool(config, 'show_preview', True)
    default_auto_start_recording = get_config_bool(config, 'auto_start_recording', False)
    default_console_output = get_config_bool(config, 'console_output', False)
    default_libcamera_log_level = get_config_str(config, 'libcamera_log_level', 'WARN').upper()
    default_gui_start_minimized = get_config_bool(config, 'gui_start_minimized', True)

    parser = argparse.ArgumentParser(description="Multi-camera recorder with preview and overlays")
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=("gui", "headless"),
        default_mode="gui",
    )

    from cli_utils import get_resolution_preset_help
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=default_resolution,
        help=f"Recording resolution preset (0-7). {get_resolution_preset_help()}",
    )

    parser.add_argument(
        "--preview-size",
        type=parse_resolution,
        default=default_preview,
        help=f"Preview window size preset (0-7). {get_resolution_preset_help()}",
    )

    parser.add_argument(
        "--target-fps",
        dest="target_fps",
        type=positive_float,
        default=default_fps,
        help="Recording frames per second",
    )
    parser.add_argument("--fps", dest="target_fps", type=positive_float, help=argparse.SUPPRESS)

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

    # Preview control
    preview_group = parser.add_mutually_exclusive_group()
    preview_group.add_argument(
        "--preview",
        dest="show_preview",
        action="store_true",
        default=default_show_preview,
        help="Show preview window (default if enabled in config)",
    )
    preview_group.add_argument(
        "--no-preview",
        dest="show_preview",
        action="store_false",
        help="Disable preview window (headless operation)",
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

    # libcamera log level control
    parser.add_argument(
        "--libcamera-log-level",
        dest="libcamera_log_level",
        choices=['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL'],
        default=default_libcamera_log_level,
        help="libcamera logging verbosity (default: WARN for clean logs)",
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
    parser.add_argument("--tkinter", dest="mode", action="store_const", const="gui", help=argparse.SUPPRESS)
    parser.add_argument("--interactive", dest="mode", action="store_const", const="gui", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    args.width, args.height = args.resolution
    args.preview_width, args.preview_height = args.preview_size
    args.fps = args.target_fps

    # Camera detection settings (hardcoded, automatically handled)
    args.min_cameras = 1
    args.allow_partial = True
    args.discovery_timeout = 5.0
    args.discovery_retry = 3.0
    args.single_camera = False  # Always support multiple cameras

    return args


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    args.output_dir = ensure_directory(args.output_dir)

    # Setup session directory and logging using shared utilities
    session_dir, session_name, log_file, is_command_mode = setup_session_from_args(
        args,
        module_name='camera',
        default_prefix='session'
    )

    # Set environment variables to control libcamera output
    # Do this BEFORE importing picamera2/libcamera
    import os
    libcam_level = args.libcamera_log_level
    os.environ['LIBCAMERA_LOG_LEVELS'] = f'Camera:{libcam_level},RPI:{libcam_level},IPAProxy:{libcam_level}'
    os.environ['LIBCAMERA_LOG_FILE'] = 'syslog'  # Disable libcamera's separate log file

    # Redirect stderr/stdout to log file BEFORE configuring logging or importing picamera2
    # Returns original stdout for user-facing messages and parent process communication
    original_stdout = redirect_stderr_stdout(log_file)

    # Configure StatusMessage to use original stdout if in command mode
    # This must be done BEFORE any imports that might send status messages
    if is_command_mode:
        from logger_core.commands import StatusMessage
        StatusMessage.configure(original_stdout)

    # Now configure Python logging
    # If console_output is True, Python logging will ALSO write to console (via StreamHandler)
    # Note: C library output (libcamera, Qt) always goes to log file only
    configure_logging(args.log_level, str(log_file), console_output=args.console_output)

    # Store session_dir and stdout streams in args so CameraSystem can use them
    args.session_dir = session_dir
    args.console_stdout = original_stdout  # For console messages
    args.command_stdout = original_stdout  # For parent process communication

    logger.info("=" * 60)
    logger.info("Camera System Starting")
    logger.info("=" * 60)
    logger.info("Session: %s", session_name)
    logger.info("Log file: %s", log_file)
    logger.info("Mode: %s", args.mode)
    logger.info("Preview: %s", args.show_preview)
    logger.info("Console output: %s", args.console_output)
    logger.info("=" * 60)

    # Import CameraSupervisor AFTER stderr/stdout redirection
    # This ensures libcamera initialization output is captured in log file
    from camera_core import CameraSupervisor

    supervisor = CameraSupervisor(args)
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
        logger.info("Camera System Stopped")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
