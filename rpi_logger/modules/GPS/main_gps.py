"""GPS module entry point built on the shared stub VMC framework.

This module manages GPS receivers that output standard NMEA sentences.
Devices are assigned by TheLogger via the assign_device command.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

MODULE_DIR = Path(__file__).resolve().parent


def _find_project_root(start: Path) -> Path:
    """Walk up until we locate the repository root (parent of rpi_logger package)."""
    for parent in start.parents:
        if parent.name == "rpi_logger":
            return parent.parent
    return start.parents[-1]


# Ensure the repository root (containing the rpi_logger package) is importable.
PROJECT_ROOT = _find_project_root(MODULE_DIR)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Re-use the stub VMC stack without copying its sources.
STUB_FRAMEWORK_DIR = MODULE_DIR.parent / "stub (codex)"
if STUB_FRAMEWORK_DIR.exists() and str(STUB_FRAMEWORK_DIR) not in sys.path:
    sys.path.insert(0, str(STUB_FRAMEWORK_DIR))

# Make sure any local virtual environment site-packages are available.
_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from vmc import StubCodexSupervisor  # noqa: E402

from gps.runtime import GPSModuleRuntime  # noqa: E402
from view import GPSView  # noqa: E402
from rpi_logger.cli.common import add_common_cli_arguments, install_signal_handlers  # noqa: E402
from rpi_logger.core.logging_utils import get_module_logger  # noqa: E402
from rpi_logger.modules.base.config_paths import resolve_module_config_path  # noqa: E402
from rpi_logger.modules.GPS.gps_core.config import load_config_file  # noqa: E402

logger = get_module_logger("MainGPS")
CONFIG_CONTEXT = resolve_module_config_path(MODULE_DIR, "gps")


def parse_args(argv: Optional[list[str]] = None):
    """Parse command-line arguments."""
    config = load_config_file(CONFIG_CONTEXT.writable_path)

    default_output = Path(config.get("output_dir", "gps_data"))
    default_session_prefix = str(config.get("session_prefix", "gps"))
    default_console = bool(config.get("console_output", False))
    default_zoom = float(config.get("zoom", 13.0))
    default_center_lat = float(config.get("center_lat", 40.7608))
    default_center_lon = float(config.get("center_lon", -111.8910))
    default_nmea_history = int(config.get("nmea_history", 30))

    parser = argparse.ArgumentParser(description="GPS shell module")

    # Use common CLI arguments for standard options
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=["gui", "headless"],
        default_mode=str(config.get("default_mode", "gui")).lower(),
        include_session_prefix=True,
        default_session_prefix=default_session_prefix,
        include_console_control=True,
        default_console_output=default_console,
        include_auto_recording=False,  # GPS doesn't use auto-recording
        include_parent_control=True,
        include_window_geometry=True,
    )

    # GPS-specific arguments
    parser.add_argument(
        "--offline-db",
        dest="offline_db",
        type=Path,
        default=config.get("offline_db", "offline_tiles.db"),
        help="Path to the offline tiles database.",
    )
    parser.add_argument(
        "--center-lat",
        type=float,
        default=default_center_lat,
        help="Initial map latitude.",
    )
    parser.add_argument(
        "--center-lon",
        type=float,
        default=default_center_lon,
        help="Initial map longitude.",
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=default_zoom,
        help="Initial map zoom level.",
    )
    parser.add_argument(
        "--nmea-history",
        dest="nmea_history",
        type=int,
        default=default_nmea_history,
        help="Number of recent NMEA sentences shown in the diagnostics panel.",
    )

    args = parser.parse_args(argv)
    args.config = config
    args.config_file_path = CONFIG_CONTEXT.writable_path
    return args


async def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for the GPS module."""
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("GPS module must be launched by the logger controller (commands disabled).")
        return

    display_name = args.config.get("display_name", "GPS")
    setattr(args, "config_path", CONFIG_CONTEXT.writable_path)

    supervisor = StubCodexSupervisor(
        args,
        MODULE_DIR,
        logger.getChild("Supervisor"),
        runtime_factory=lambda context: GPSModuleRuntime(context),
        view_factory=GPSView,
        display_name=display_name,
        module_id="gps",
        config_path=CONFIG_CONTEXT.writable_path,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(supervisor, loop)

    await supervisor.run()


if __name__ == "__main__":
    asyncio.run(main())
