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
from camera_core import load_config_file, CameraSupervisor

logger = logging.getLogger("CameraMain")


def parse_args(argv: Optional[list[str]] = None):
    # Load config file first
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
    default_resolution = (
        get_config_int('resolution_width', 1920),
        get_config_int('resolution_height', 1080)
    )
    default_preview = (
        get_config_int('preview_width', 640),
        get_config_int('preview_height', 360)
    )
    default_fps = get_config_float('target_fps', 30.0)
    default_min_cameras = get_config_int('min_cameras', 2)
    default_allow_partial = get_config_bool('allow_partial', False)
    default_discovery_timeout = get_config_float('discovery_timeout', 5.0)
    default_discovery_retry = get_config_float('discovery_retry', 3.0)
    default_output = Path(get_config_str('output_dir', 'recordings'))
    default_session_prefix = get_config_str('session_prefix', 'session')

    parser = argparse.ArgumentParser(description="Multi-camera recorder with preview and overlays")
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=("interactive", "headless", "slave"),
        default_mode="interactive",
    )

    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=default_resolution,
        help="Recording resolution as WIDTHxHEIGHT",
    )
    parser.add_argument("--width", dest="legacy_width", type=positive_int, help=argparse.SUPPRESS)
    parser.add_argument("--height", dest="legacy_height", type=positive_int, help=argparse.SUPPRESS)

    parser.add_argument(
        "--preview-size",
        type=parse_resolution,
        default=default_preview,
        help="Preview window size as WIDTHxHEIGHT",
    )
    parser.add_argument("--preview-width", dest="legacy_preview_width", type=positive_int, help=argparse.SUPPRESS)
    parser.add_argument("--preview-height", dest="legacy_preview_height", type=positive_int, help=argparse.SUPPRESS)

    parser.add_argument(
        "--target-fps",
        dest="target_fps",
        type=positive_float,
        default=default_fps,
        help="Recording frames per second",
    )
    parser.add_argument("--fps", dest="target_fps", type=positive_float, help=argparse.SUPPRESS)

    parser.add_argument(
        "--discovery-timeout",
        type=positive_float,
        default=default_discovery_timeout,
        help="Seconds to wait for camera discovery",
    )
    parser.add_argument(
        "--discovery-retry",
        type=positive_float,
        default=default_discovery_retry,
        help="Seconds to wait before retrying discovery when cameras are absent",
    )

    parser.add_argument(
        "--min-cameras",
        type=positive_int,
        default=default_min_cameras,
        help="Minimum number of cameras required at startup",
    )
    parser.add_argument("--single-camera", dest="min_cameras", action="store_const", const=1, help=argparse.SUPPRESS)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        default=default_allow_partial,
        help="Allow running with fewer cameras than the minimum",
    )
    parser.add_argument(
        "--session-prefix",
        type=str,
        default=default_session_prefix,
        help="Prefix for generated recording sessions",
    )
    parser.add_argument("--slave", dest="mode", action="store_const", const="slave", help=argparse.SUPPRESS)
    parser.add_argument("--headless", dest="mode", action="store_const", const="headless", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if getattr(args, "legacy_width", None) and getattr(args, "legacy_height", None):
        args.resolution = (args.legacy_width, args.legacy_height)
    if getattr(args, "legacy_preview_width", None) and getattr(args, "legacy_preview_height", None):
        args.preview_size = (args.legacy_preview_width, args.legacy_preview_height)

    args.width, args.height = args.resolution
    args.preview_width, args.preview_height = args.preview_size
    args.fps = args.target_fps
    args.single_camera = args.min_cameras <= 1

    return args


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    configure_logging(args.log_level, args.log_file)
    args.output_dir = ensure_directory(args.output_dir)

    supervisor = CameraSupervisor(args)
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(supervisor.shutdown()))

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
