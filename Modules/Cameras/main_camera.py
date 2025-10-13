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

# Add parent directories to path for imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cli_utils import (
    add_common_cli_arguments,
    configure_logging,
    ensure_directory,
    parse_resolution,
    positive_float,
    positive_int,
)
# Note: camera_core import is delayed until after stderr/stdout redirection
# This ensures libcamera output is captured in the log file

logger = logging.getLogger("CameraMain")


def parse_args(argv: Optional[list[str]] = None):
    # Load config file first (import here to avoid loading picamera2 early)
    from camera_core import load_config_file
    config = load_config_file()

    # Get defaults from config file or use hardcoded defaults
    def get_config_int(key, default):
        return int(config.get(key, default)) if key in config else default

    def get_config_float(key, default):
        return float(config.get(key, default)) if key in config else default

    def get_config_bool(key, default):
        if key in config:
            return config[key].lower() in ('true', '1', 'yes', 'on')
        return default

    def get_config_str(key, default):
        return config.get(key, default)

    # Apply config defaults
    # Handle resolution preset from config (must be number 0-5)
    from cli_utils import parse_resolution as parse_res_helper
    resolution_preset_str = get_config_str('resolution_preset', '0')
    default_resolution = parse_res_helper(resolution_preset_str)

    preview_preset_str = get_config_str('preview_preset', '5')
    default_preview = parse_res_helper(preview_preset_str)
    default_fps = get_config_float('target_fps', 30.0)
    default_output = Path(get_config_str('output_dir', 'recordings'))
    default_session_prefix = get_config_str('session_prefix', 'session')
    default_show_preview = get_config_bool('show_preview', True)
    default_auto_start_recording = get_config_bool('auto_start_recording', False)
    default_console_output = get_config_bool('console_output', False)
    default_libcamera_log_level = get_config_str('libcamera_log_level', 'WARN').upper()

    parser = argparse.ArgumentParser(description="Multi-camera recorder with preview and overlays")
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=("interactive", "headless", "slave"),
        default_mode="interactive",
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

    parser.add_argument("--slave", dest="mode", action="store_const", const="slave", help=argparse.SUPPRESS)
    parser.add_argument("--headless", dest="mode", action="store_const", const="headless", help=argparse.SUPPRESS)

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


class AnsiStripWriter:
    """
    File wrapper that strips ANSI escape codes before writing.
    This cleans up colored output from C libraries (libcamera).
    Optimized to only run regex if ANSI codes are detected.
    """
    def __init__(self, file_obj):
        self.file = file_obj
        # ANSI escape sequence pattern
        import re
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def write(self, data):
        # Fast path: only strip if ANSI codes are present
        # Most Python logging doesn't contain ANSI codes
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
    - C/C++ library output (libcamera, Qt, OpenCV)

    ANSI color codes are stripped for clean log output.

    Args:
        log_file_path: Path to log file

    Returns:
        Original stdout file object for user-facing messages
    """
    import os
    import sys

    # Preserve original stdout for user-facing messages
    # We need to duplicate the file descriptor before redirecting
    original_stdout_fd = os.dup(sys.stdout.fileno())
    original_stdout = os.fdopen(original_stdout_fd, 'w', buffering=1)

    # Open log file in append mode
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
    # These will clean up colored output from libcamera
    sys.stderr = clean_log
    sys.stdout = clean_log

    return original_stdout


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    args.output_dir = ensure_directory(args.output_dir)

    # Create session directory for logging and recordings
    import datetime
    import os
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.session_prefix.rstrip("_")
    session_name = f"{prefix}_{timestamp}" if prefix else timestamp
    session_dir = args.output_dir / session_name
    session_dir.mkdir(parents=True, exist_ok=True)

    # Configure logging to session directory
    log_file = session_dir / "session.log"

    # Set environment variables to control libcamera output
    # Do this BEFORE importing picamera2/libcamera
    libcam_level = args.libcamera_log_level
    os.environ['LIBCAMERA_LOG_LEVELS'] = f'Camera:{libcam_level},RPI:{libcam_level},IPAProxy:{libcam_level}'
    os.environ['LIBCAMERA_LOG_FILE'] = 'syslog'  # Disable libcamera's separate log file
    # Note: We don't set NO_COLOR because we strip ANSI codes anyway

    # Redirect stderr/stdout to log file BEFORE configuring logging or importing picamera2
    # This captures ALL output:
    # - Python logging
    # - C/C++ library output (libcamera, Qt, OpenCV)
    # ANSI color codes are automatically stripped
    # Returns original stdout for user-facing messages
    original_stdout = redirect_stderr_stdout(log_file)

    # Now configure Python logging
    # If console_output is True, Python logging will ALSO write to console (via StreamHandler)
    # Note: C library output (libcamera, Qt) always goes to log file only
    configure_logging(args.log_level, str(log_file), console_output=args.console_output)

    # Store session_dir and console_stdout in args so CameraSystem can use them
    args.session_dir = session_dir
    args.console_stdout = original_stdout

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

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(supervisor.shutdown()))

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()
        logger.info("=" * 60)
        logger.info("Camera System Stopped")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
