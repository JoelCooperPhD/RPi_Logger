"""EyeTracker module entry point leveraging the stub (codex) VMC stack."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

MODULE_DIR = Path(__file__).resolve().parent.parent


def _find_project_root(start: Path) -> Path:
    for parent in start.parents:
        if parent.name == "rpi_logger":
            return parent.parent
    return start.parents[-1]


PROJECT_ROOT = _find_project_root(MODULE_DIR)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if __package__ in {None, ""}:
    __package__ = "rpi_logger.modules.EyeTracker"

if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from rpi_logger.cli.common import (
    add_common_cli_arguments,
    parse_resolution,
    positive_float,
    positive_int,
    get_config_int,
    get_config_float,
    get_config_bool,
    get_config_str,
    install_signal_handlers,
)
from rpi_logger.core.logging_utils import get_module_logger
from vmc import StubCodexSupervisor, RuntimeRetryPolicy

from rpi_logger.modules.EyeTracker.tracker_core.config import load_config_file

from .eye_tracker_runtime import EyeTrackerRuntime

DISPLAY_NAME = "EyeTracker"
MODULE_ID = "eye_tracker"
DEFAULT_OUTPUT_SUBDIR = Path("eye-tracker")

logger = get_module_logger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    config_path = MODULE_DIR / "config.txt"
    config = load_config_file(config_path)

    default_output = Path(get_config_str(config, "output_dir", DEFAULT_OUTPUT_SUBDIR))
    default_session_prefix = get_config_str(config, "session_prefix", MODULE_ID)
    default_console = get_config_bool(config, "console_output", False)
    default_auto_start = get_config_bool(config, "auto_start_recording", False)

    default_width = get_config_int(config, "resolution_width", 1280)
    default_height = get_config_int(config, "resolution_height", 720)
    default_resolution = (default_width, default_height)
    default_fps = get_config_float(config, "target_fps", 5.0)
    
    # Default to 640x480 to match Cameras module and ensure good performance
    default_preview_width = get_config_int(config, "preview_width", 640)
    default_preview_height = get_config_int(config, "preview_height", 480)

    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=("gui", "headless"),
        default_mode="gui",
        default_session_prefix=default_session_prefix,
        default_console_output=default_console,
        default_auto_start_recording=default_auto_start,
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
        help="Scene video resolution preset (see rpi_logger.cli.common.RESOLUTION_PRESETS)",
    )
    parser.add_argument(
        "--preview-width",
        type=positive_int,
        default=default_preview_width,
        help="Preview canvas width in pixels (height maintains 4:3)",
    )
    parser.add_argument(
        "--discovery-timeout",
        dest="discovery_timeout",
        type=positive_float,
        default=get_config_float(config, "discovery_timeout", 5.0),
        help="Device discovery timeout in seconds",
    )
    parser.add_argument(
        "--discovery-retry",
        dest="discovery_retry",
        type=positive_float,
        default=get_config_float(config, "discovery_retry", 3.0),
        help="Retry interval between discovery attempts",
    )
    parser.add_argument(
        "--gui-preview-update-hz",
        dest="gui_preview_update_hz",
        type=positive_int,
        default=get_config_int(config, "gui_preview_update_hz", 10),
        help="Preview refresh rate in Hz",
    )

    parser.add_argument(
        "--advanced-gaze-logging",
        dest="enable_advanced_gaze_logging",
        action="store_true",
        help="Enable extended gaze CSV logging",
    )
    parser.add_argument(
        "--no-advanced-gaze-logging",
        dest="enable_advanced_gaze_logging",
        action="store_false",
        help="Disable extended gaze CSV logging",
    )
    parser.add_argument(
        "--enable-eye-event-details",
        dest="expand_eye_event_details",
        action="store_true",
        help="Include fixation/blink details in events CSV",
    )
    parser.add_argument(
        "--disable-eye-event-details",
        dest="expand_eye_event_details",
        action="store_false",
        help="Write compact legacy event CSV",
    )
    parser.add_argument(
        "--enable-audio-recording",
        dest="enable_audio_recording",
        action="store_true",
        help="Capture headset audio stream",
    )
    parser.add_argument(
        "--disable-audio-recording",
        dest="enable_audio_recording",
        action="store_false",
        help="Disable headset audio stream",
    )
    parser.add_argument(
        "--audio-stream-param",
        dest="audio_stream_param",
        default=get_config_str(config, "audio_stream_param", "audio=scene"),
        help="RTSP query parameter used to locate audio stream",
    )
    parser.add_argument(
        "--log-device-status",
        dest="enable_device_status_logging",
        action="store_true",
        help="Record periodic device telemetry",
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
        default=get_config_float(config, "device_status_poll_interval", 5.0),
        help="Seconds between telemetry samples",
    )

    parser.set_defaults(
        enable_advanced_gaze_logging=get_config_bool(config, "enable_advanced_gaze_logging", False),
        expand_eye_event_details=get_config_bool(config, "expand_eye_event_details", True),
        enable_audio_recording=get_config_bool(config, "enable_audio_recording", False),
        enable_device_status_logging=get_config_bool(config, "enable_device_status_logging", False),
    )

    args = parser.parse_args(argv)

    args.width, args.height = args.resolution
    args.preview_width = getattr(args, "preview_width", default_preview_width)
    args.preview_height = int(args.preview_width * 3 / 4)

    args.enable_recording_overlay = get_config_bool(config, "enable_recording_overlay", True)
    args.include_gaze_in_recording = get_config_bool(config, "include_gaze_in_recording", True)
    args.overlay_font_scale = get_config_float(config, "overlay_font_scale", 0.6)
    args.overlay_thickness = get_config_int(config, "overlay_thickness", 1)
    args.overlay_color_r = get_config_int(config, "overlay_color_r", 0)
    args.overlay_color_g = get_config_int(config, "overlay_color_g", 0)
    args.overlay_color_b = get_config_int(config, "overlay_color_b", 0)
    args.overlay_margin_left = get_config_int(config, "overlay_margin_left", 10)
    args.overlay_line_start_y = get_config_int(config, "overlay_line_start_y", 30)
    args.gaze_circle_radius = get_config_int(config, "gaze_circle_radius", 10)
    args.gaze_circle_thickness = get_config_int(config, "gaze_circle_thickness", 1)
    args.gaze_center_radius = get_config_int(config, "gaze_center_radius", 1)
    args.gaze_shape = get_config_str(config, "gaze_shape", "circle")
    args.gaze_color_worn_b = get_config_int(config, "gaze_color_worn_b", 255)
    args.gaze_color_worn_g = get_config_int(config, "gaze_color_worn_g", 255)
    args.gaze_color_worn_r = get_config_int(config, "gaze_color_worn_r", 0)
    args.gaze_color_not_worn_b = get_config_int(config, "gaze_color_not_worn_b", 0)
    args.gaze_color_not_worn_g = get_config_int(config, "gaze_color_not_worn_g", 0)
    args.gaze_color_not_worn_r = get_config_int(config, "gaze_color_not_worn_r", 255)

    args.config = config
    args.config_file_path = config_path

    return args


def build_runtime(context):
    return EyeTrackerRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not getattr(args, "enable_commands", False):
        logger.error("EyeTracker module must be launched by the logger controller.")
        return

    def show_eyetracker_help(parent):
        from rpi_logger.modules.EyeTracker.tracker_core.interfaces.gui.help_dialog import EyeTrackerHelpDialog
        EyeTrackerHelpDialog(parent)

    supervisor = StubCodexSupervisor(
        args,
        MODULE_DIR,
        logger,
        runtime_factory=build_runtime,
        runtime_retry_policy=RuntimeRetryPolicy(interval=3.0, max_attempts=3),
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
        help_callback=show_eyetracker_help,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(supervisor, loop)

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
