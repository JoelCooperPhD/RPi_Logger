
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
    from rpi_logger.cli.common import (
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
    config_path = Path(__file__).parent / "config.txt"
    config = load_config_file(config_path)

    # Preview resolution presets (4:3 aspect ratio - matches Pupil Labs 1600x1200 scene camera)
    PREVIEW_PRESETS = {
        0: (1600, 1200),  # Full - Native resolution
        1: (1280, 960),   # Large - High quality
        2: (1024, 768),   # XGA - Good balance
        3: (800, 600),    # SVGA - Standard quality
        4: (640, 480),    # VGA - Balanced (default)
        5: (480, 360),    # Small - Low CPU
        6: (320, 240),    # QVGA - Minimal CPU
        7: (240, 180),    # Tiny - Very low CPU
        8: (160, 120),    # Micro - Ultra minimal
    }

    default_width = get_config_int(config, 'resolution_width', 1280)
    default_height = get_config_int(config, 'resolution_height', 720)
    default_resolution = (default_width, default_height)
    default_fps = get_config_float(config, 'target_fps', 5.0)
    default_output = Path(get_config_str(config, 'output_dir', 'recordings'))
    default_session_prefix = get_config_str(config, 'session_prefix', 'tracking')

    # Load preview preset (with fallback to old preview_width if preset not found)
    preview_preset = get_config_int(config, 'preview_preset', -1)
    if preview_preset in PREVIEW_PRESETS:
        default_preview_width, default_preview_height = PREVIEW_PRESETS[preview_preset]
    else:
        # Fallback to old config style if preview_width exists
        default_preview_width = get_config_int(config, 'preview_width', 640)
        # Calculate height maintaining 4:3 aspect ratio (Pupil Labs scene camera)
        default_preview_height = int(default_preview_width * 3 / 4)
    default_auto_start_recording = get_config_bool(config, 'auto_start_recording', False)
    default_console_output = get_config_bool(config, 'console_output', False)
    default_discovery_timeout = get_config_float(config, 'discovery_timeout', 5.0)
    default_discovery_retry = get_config_float(config, 'discovery_retry', 3.0)
    default_gui_preview_update_hz = get_config_int(config, 'gui_preview_update_hz', 10)

    # Recording overlay settings
    default_enable_recording_overlay = get_config_bool(config, 'enable_recording_overlay', True)
    default_include_gaze_in_recording = get_config_bool(config, 'include_gaze_in_recording', True)
    default_overlay_font_scale = get_config_float(config, 'overlay_font_scale', 0.6)
    default_overlay_thickness = get_config_int(config, 'overlay_thickness', 1)
    default_overlay_color_r = get_config_int(config, 'overlay_color_r', 0)
    default_overlay_color_g = get_config_int(config, 'overlay_color_g', 0)
    default_overlay_color_b = get_config_int(config, 'overlay_color_b', 0)
    default_overlay_margin_left = get_config_int(config, 'overlay_margin_left', 10)
    default_overlay_line_start_y = get_config_int(config, 'overlay_line_start_y', 30)

    # Gaze indicator settings
    default_gaze_circle_radius = get_config_int(config, 'gaze_circle_radius', 30)
    default_gaze_circle_thickness = get_config_int(config, 'gaze_circle_thickness', 3)
    default_gaze_center_radius = get_config_int(config, 'gaze_center_radius', 2)
    default_gaze_shape = get_config_str(config, 'gaze_shape', 'circle')
    default_gaze_color_worn_b = get_config_int(config, 'gaze_color_worn_b', 255)
    default_gaze_color_worn_g = get_config_int(config, 'gaze_color_worn_g', 255)
    default_gaze_color_worn_r = get_config_int(config, 'gaze_color_worn_r', 0)
    default_gaze_color_not_worn_b = get_config_int(config, 'gaze_color_not_worn_b', 0)
    default_gaze_color_not_worn_g = get_config_int(config, 'gaze_color_not_worn_g', 0)
    default_gaze_color_not_worn_r = get_config_int(config, 'gaze_color_not_worn_r', 255)

    default_enable_advanced_gaze_logging = get_config_bool(config, 'enable_advanced_gaze_logging', False)
    default_expand_eye_event_details = get_config_bool(config, 'expand_eye_event_details', True)
    default_enable_audio_recording = get_config_bool(config, 'enable_audio_recording', False)
    default_audio_stream_param = get_config_str(config, 'audio_stream_param', 'audio=scene')
    default_enable_device_status_logging = get_config_bool(config, 'enable_device_status_logging', False)
    default_device_status_poll_interval = get_config_float(config, 'device_status_poll_interval', 5.0)

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

    parser.add_argument(
        "--gui-preview-update-hz",
        dest="gui_preview_update_hz",
        type=positive_int,
        default=default_gui_preview_update_hz,
        help="GUI preview update rate in Hz (1-30)",
    )

    parser.add_argument(
        "--advanced-gaze-logging",
        dest="enable_advanced_gaze_logging",
        action="store_true",
        help="Enable extended gaze CSV with per-eye metrics",
    )
    parser.add_argument(
        "--no-advanced-gaze-logging",
        dest="enable_advanced_gaze_logging",
        action="store_false",
        help="Disable extended gaze CSV output",
    )

    parser.add_argument(
        "--enable-eye-event-details",
        dest="expand_eye_event_details",
        action="store_true",
        help="Include detailed fixation/blink fields in event CSV",
    )
    parser.add_argument(
        "--disable-eye-event-details",
        dest="expand_eye_event_details",
        action="store_false",
        help="Write legacy compact eye events CSV",
    )

    parser.add_argument(
        "--enable-audio-recording",
        dest="enable_audio_recording",
        action="store_true",
        help="Record headset audio alongside gaze streams",
    )
    parser.add_argument(
        "--disable-audio-recording",
        dest="enable_audio_recording",
        action="store_false",
        help="Skip audio capture even if enabled in config",
    )

    parser.add_argument(
        "--audio-stream-param",
        dest="audio_stream_param",
        default=default_audio_stream_param,
        help="Custom RTSP query parameter for audio stream discovery (default: audio=scene)",
    )

    parser.add_argument(
        "--log-device-status",
        dest="enable_device_status_logging",
        action="store_true",
        help="Persist periodic device telemetry to CSV",
    )
    parser.add_argument(
        "--no-log-device-status",
        dest="enable_device_status_logging",
        action="store_false",
        help="Disable device telemetry logging",
    )

    parser.add_argument(
        "--device-status-interval",
        dest="device_status_poll_interval",
        type=positive_float,
        default=default_device_status_poll_interval,
        help="Polling interval (s) when recording device status",
    )

    parser.add_argument("--slave", dest="mode", action="store_const", const="slave", help=argparse.SUPPRESS)
    parser.add_argument("--tkinter", dest="mode", action="store_const", const="gui", help=argparse.SUPPRESS)

    parser.set_defaults(
        enable_advanced_gaze_logging=default_enable_advanced_gaze_logging,
        expand_eye_event_details=default_expand_eye_event_details,
        enable_audio_recording=default_enable_audio_recording,
        enable_device_status_logging=default_enable_device_status_logging,
    )

    args = parser.parse_args(argv)

    args.width, args.height = args.resolution

    # Add preview resolution from preset
    args.preview_width = default_preview_width
    args.preview_height = default_preview_height

    # Add overlay config values to args
    args.enable_recording_overlay = default_enable_recording_overlay
    args.include_gaze_in_recording = default_include_gaze_in_recording
    args.overlay_font_scale = default_overlay_font_scale
    args.overlay_thickness = default_overlay_thickness
    args.overlay_color_r = default_overlay_color_r
    args.overlay_color_g = default_overlay_color_g
    args.overlay_color_b = default_overlay_color_b
    args.overlay_margin_left = default_overlay_margin_left
    args.overlay_line_start_y = default_overlay_line_start_y

    # Add gaze indicator config values to args
    args.gaze_circle_radius = default_gaze_circle_radius
    args.gaze_circle_thickness = default_gaze_circle_thickness
    args.gaze_center_radius = default_gaze_center_radius
    args.gaze_shape = default_gaze_shape
    args.gaze_color_worn_b = default_gaze_color_worn_b
    args.gaze_color_worn_g = default_gaze_color_worn_g
    args.gaze_color_worn_r = default_gaze_color_worn_r
    args.gaze_color_not_worn_b = default_gaze_color_not_worn_b
    args.gaze_color_not_worn_g = default_gaze_color_not_worn_g
    args.gaze_color_not_worn_r = default_gaze_color_not_worn_r

    from rpi_logger.modules.base import load_window_geometry_from_config
    args.window_geometry = load_window_geometry_from_config(config, args.window_geometry)

    args.config = config
    args.config_file_path = config_path

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
    install_signal_handlers(supervisor, loop, track_shutdown_state=True)

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
