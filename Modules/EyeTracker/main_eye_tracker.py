
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

try:
    from cli_utils import (
        add_common_cli_arguments,
        ensure_directory,
        parse_resolution,
        positive_float,
        positive_int,
        get_config_int,
        get_config_float,
        get_config_bool,
        get_config_str,
        setup_module_logging,
        install_exception_handlers,
        install_signal_handlers,
        log_module_startup,
        log_module_shutdown,
    )
except ImportError as e:
    print(f"ERROR: Cannot import required modules. Ensure PYTHONPATH includes project root or install package.", file=sys.stderr)
    print(f"  Add to PYTHONPATH: export PYTHONPATH=/home/rs-pi-2/Development/RPi_Logger:$PYTHONPATH", file=sys.stderr)
    print(f"  Or install package: cd /home/rs-pi-2/Development/RPi_Logger && pip install -e .", file=sys.stderr)
    sys.exit(1)

logger = logging.getLogger("TrackerMain")


def parse_args(argv: Optional[list[str]] = None):
    from tracker_core import load_config_file
    config = load_config_file()

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
        default_session_prefix=default_session_prefix,
        default_console_output=default_console_output,
        default_auto_start_recording=default_auto_start_recording,
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

    parser.add_argument(
        "--gui-preview-update-hz",
        dest="gui_preview_update_hz",
        type=positive_int,
        default=default_gui_preview_update_hz,
        help="GUI preview update rate in Hz (1-30)",
    )

    parser.add_argument("--slave", dest="mode", action="store_const", const="slave", help=argparse.SUPPRESS)
    parser.add_argument("--tkinter", dest="mode", action="store_const", const="gui", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    args.width, args.height = args.resolution

    from Modules.base import load_window_geometry_from_config
    args.window_geometry = load_window_geometry_from_config(config, args.window_geometry)

    return args


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    args.output_dir = ensure_directory(args.output_dir)

    module_dir = Path(__file__).parent
    session_name, log_file, is_command_mode = setup_module_logging(
        args,
        module_name='eyetracker',
        module_dir=module_dir,
        default_prefix='tracking'
    )

    log_module_startup(
        logger,
        session_name,
        log_file,
        args,
        module_name="Eye Tracker",
        target_fps=f"{args.target_fps:.1f}",
        resolution=f"{args.width}x{args.height}",
    )

    # Import TrackerSupervisor AFTER stderr/stdout redirection
    from tracker_core import TrackerSupervisor

    supervisor = TrackerSupervisor(args)
    loop = asyncio.get_running_loop()

    install_exception_handlers(logger, loop)
    install_signal_handlers(supervisor, loop)

    try:
        await supervisor.run()
    except Exception as e:
        logger.exception("Unhandled exception in main: %s", e)
        raise  # Re-raise to preserve exit code
    finally:
        await supervisor.shutdown()
        log_module_shutdown(logger, "Eye Tracker")


if __name__ == "__main__":
    asyncio.run(main())
