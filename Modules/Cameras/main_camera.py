
import argparse
import asyncio
import contextlib
import logging
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
# Note: camera_core import is delayed until after stderr/stdout redirection

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    # Load config file first (import here to avoid loading picamera2 early)
    from camera_core import load_config_file
    config = load_config_file()

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
        default_session_prefix=default_session_prefix,
        default_console_output=default_console_output,
        default_auto_start_recording=default_auto_start_recording,
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

    parser.add_argument(
        "--libcamera-log-level",
        dest="libcamera_log_level",
        choices=['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL'],
        default=default_libcamera_log_level,
        help="libcamera logging verbosity (default: WARN for clean logs)",
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

    parser.add_argument("--slave", dest="mode", action="store_const", const="slave", help=argparse.SUPPRESS)
    parser.add_argument("--headless", dest="mode", action="store_const", const="headless", help=argparse.SUPPRESS)
    parser.add_argument("--tkinter", dest="mode", action="store_const", const="gui", help=argparse.SUPPRESS)
    parser.add_argument("--interactive", dest="mode", action="store_const", const="gui", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    args.width, args.height = args.resolution
    args.preview_width, args.preview_height = args.preview_size
    args.fps = args.target_fps

    args.min_cameras = 1
    args.allow_partial = True
    args.discovery_timeout = 5.0
    args.discovery_retry = 3.0
    args.single_camera = False  # Always support multiple cameras

    from Modules.base import load_window_geometry_from_config
    args.window_geometry = load_window_geometry_from_config(config, args.window_geometry)

    return args


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    args.output_dir = ensure_directory(args.output_dir)

    # Do this BEFORE importing picamera2/libcamera and before logging setup
    import os
    libcam_level = args.libcamera_log_level
    os.environ['LIBCAMERA_LOG_LEVELS'] = f'Camera:{libcam_level},RPI:{libcam_level},IPAProxy:{libcam_level}'
    os.environ['LIBCAMERA_LOG_FILE'] = 'syslog'  # Disable libcamera's separate log file

    module_dir = Path(__file__).parent
    session_name, log_file, is_command_mode = setup_module_logging(
        args,
        module_name='camera',
        module_dir=module_dir,
        default_prefix='session'
    )

    log_module_startup(
        logger,
        session_name,
        log_file,
        args,
        module_name="Camera",
        preview=args.show_preview,
    )

    # Import CameraSupervisor AFTER stderr/stdout redirection
    from camera_core import CameraSupervisor

    supervisor = CameraSupervisor(args)
    loop = asyncio.get_running_loop()

    install_exception_handlers(logger, loop)
    install_signal_handlers(supervisor, loop, track_shutdown_state=True)

    try:
        await supervisor.run()
    except Exception as e:
        logger.exception("Unhandled exception in main: %s", e)
        raise  # Re-raise to preserve exit code
    finally:
        await supervisor.shutdown()
        log_module_shutdown(logger, "Camera")


if __name__ == "__main__":
    asyncio.run(main())
