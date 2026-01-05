"""Neon EyeTracker module entry point leveraging the stub (codex) VMC stack."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

MODULE_DIR = Path(__file__).resolve().parent


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

from dataclasses import asdict

from rpi_logger.cli.common import (
    add_common_cli_arguments,
    add_config_to_args,
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
from rpi_logger.modules.base.config_paths import resolve_module_config_path
from vmc import StubCodexSupervisor, RuntimeRetryPolicy

from .app.eye_tracker_runtime import EyeTrackerRuntime
from .app.view import NeonEyeTrackerView
from .config import EyeTrackerConfig

DISPLAY_NAME = "EyeTracker-Neon"
MODULE_ID = "neon_eyetracker"
DEFAULT_OUTPUT_SUBDIR = Path("neon-eyetracker")

logger = get_module_logger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    config_ctx = resolve_module_config_path(MODULE_DIR, MODULE_ID)
    defaults = asdict(EyeTrackerConfig())

    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")

    # Load config using unified helper
    config = add_config_to_args(parser, config_ctx, defaults)

    default_output = Path(get_config_str(config, "output_dir", str(DEFAULT_OUTPUT_SUBDIR)))
    default_session_prefix = get_config_str(config, "session_prefix", defaults["session_prefix"])
    default_console = get_config_bool(config, "console_output", defaults["console_output"])
    default_auto_start = get_config_bool(config, "auto_start_recording", defaults["auto_start_recording"])

    default_width = get_config_int(config, "resolution_width", defaults["resolution_width"])
    default_height = get_config_int(config, "resolution_height", defaults["resolution_height"])
    default_resolution = (default_width, default_height)
    default_fps = get_config_float(config, "target_fps", defaults["target_fps"])

    default_preview_width = get_config_int(config, "preview_width", defaults["preview_width"])

    add_common_cli_arguments(
        parser,
        default_output=default_output,
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
        default=get_config_float(config, "discovery_timeout", defaults["discovery_timeout"]),
        help="Device discovery timeout in seconds",
    )
    parser.add_argument(
        "--discovery-retry",
        dest="discovery_retry",
        type=positive_float,
        default=get_config_float(config, "discovery_retry", defaults["discovery_retry"]),
        help="Retry interval between discovery attempts",
    )
    parser.add_argument(
        "--gui-preview-update-hz",
        dest="gui_preview_update_hz",
        type=positive_int,
        default=get_config_int(config, "gui_preview_update_hz", defaults["gui_preview_update_hz"]),
        help="Preview refresh rate in Hz",
    )

    parser.add_argument(
        "--audio-stream-param",
        dest="audio_stream_param",
        default=get_config_str(config, "audio_stream_param", defaults["audio_stream_param"]),
        help="RTSP query parameter used to locate audio stream",
    )

    args = parser.parse_args(argv)

    args.width, args.height = args.resolution
    args.preview_width = getattr(args, "preview_width", default_preview_width)
    args.preview_height = int(args.preview_width * 3 / 4)

    # Store overlay and gaze settings from config (will be loaded via typed config in runtime)
    args.enable_recording_overlay = get_config_bool(config, "enable_recording_overlay", True)
    args.include_gaze_in_recording = get_config_bool(config, "include_gaze_in_recording", True)
    args.overlay_font_scale = get_config_float(config, "overlay_font_scale", 0.6)
    args.overlay_thickness = get_config_int(config, "overlay_thickness", 2)
    args.overlay_color_r = get_config_int(config, "overlay_color_r", 255)
    args.overlay_color_g = get_config_int(config, "overlay_color_g", 255)
    args.overlay_color_b = get_config_int(config, "overlay_color_b", 255)
    args.overlay_margin_left = get_config_int(config, "overlay_margin_left", 10)
    args.overlay_line_start_y = get_config_int(config, "overlay_line_start_y", 30)
    args.gaze_circle_radius = get_config_int(config, "gaze_circle_radius", 60)
    args.gaze_circle_thickness = get_config_int(config, "gaze_circle_thickness", 6)
    args.gaze_center_radius = get_config_int(config, "gaze_center_radius", 4)
    args.gaze_shape = get_config_str(config, "gaze_shape", "circle")
    args.gaze_color_worn_b = get_config_int(config, "gaze_color_worn_b", 0)
    args.gaze_color_worn_g = get_config_int(config, "gaze_color_worn_g", 0)
    args.gaze_color_worn_r = get_config_int(config, "gaze_color_worn_r", 255)

    # Stream viewer enable states (Controls menu persistence)
    args.stream_video_enabled = get_config_bool(config, "stream_video_enabled", True)
    args.stream_gaze_enabled = get_config_bool(config, "stream_gaze_enabled", True)
    args.stream_eyes_enabled = get_config_bool(config, "stream_eyes_enabled", True)
    args.stream_imu_enabled = get_config_bool(config, "stream_imu_enabled", True)
    args.stream_events_enabled = get_config_bool(config, "stream_events_enabled", True)
    args.stream_audio_enabled = get_config_bool(config, "stream_audio_enabled", True)

    # config_path is set by add_config_to_args
    return args


def build_runtime(context):
    return EyeTrackerRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not getattr(args, "enable_commands", False):
        logger.error("EyeTracker-Neon module must be launched by the logger controller.")
        return

    def show_eyetracker_help(parent):
        from rpi_logger.modules.EyeTracker.tracker_core.interfaces.gui.help_dialog import EyeTrackerHelpDialog
        EyeTrackerHelpDialog(parent)

    # config_path is set by add_config_to_args in parse_args
    config_path = getattr(args, "config_path", None)

    supervisor = StubCodexSupervisor(
        args,
        MODULE_DIR,
        logger,
        runtime_factory=build_runtime,
        runtime_retry_policy=RuntimeRetryPolicy(interval=3.0, max_attempts=3),
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
        config_path=config_path,
        view_factory=NeonEyeTrackerView,
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
