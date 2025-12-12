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

from dataclasses import asdict  # noqa: E402

from vmc import StubCodexSupervisor  # noqa: E402

from gps.runtime import GPSModuleRuntime  # noqa: E402
from view import GPSView  # noqa: E402
from rpi_logger.cli.common import add_common_cli_arguments, add_config_to_args, install_signal_handlers  # noqa: E402
from rpi_logger.core.logging_utils import get_module_logger  # noqa: E402
from rpi_logger.modules.base.config_paths import resolve_module_config_path  # noqa: E402

from .config import GPSConfig  # noqa: E402

logger = get_module_logger("MainGPS")
MODULE_ID = "gps"


def parse_args(argv: Optional[list[str]] = None):
    """Parse command-line arguments."""
    config_ctx = resolve_module_config_path(MODULE_DIR, MODULE_ID)
    defaults = asdict(GPSConfig())

    parser = argparse.ArgumentParser(description="GPS shell module")

    # Load config using unified helper
    config = add_config_to_args(parser, config_ctx, defaults)

    # Use common CLI arguments for standard options
    add_common_cli_arguments(
        parser,
        default_output=Path(config.get("output_dir", defaults["output_dir"])),
        allowed_modes=["gui", "headless"],
        default_mode=str(config.get("default_mode", defaults["default_mode"])).lower(),
        include_session_prefix=True,
        default_session_prefix=str(config.get("session_prefix", defaults["session_prefix"])),
        include_console_control=True,
        default_console_output=bool(config.get("console_output", defaults["console_output"])),
        include_auto_recording=False,  # GPS doesn't use auto-recording
        include_parent_control=True,
        include_window_geometry=True,
    )

    # GPS-specific arguments
    parser.add_argument(
        "--offline-db",
        dest="offline_db",
        type=Path,
        default=config.get("offline_db", defaults["offline_db"]),
        help="Path to the offline tiles database.",
    )
    parser.add_argument(
        "--center-lat",
        type=float,
        default=float(config.get("center_lat", defaults["center_lat"])),
        help="Initial map latitude.",
    )
    parser.add_argument(
        "--center-lon",
        type=float,
        default=float(config.get("center_lon", defaults["center_lon"])),
        help="Initial map longitude.",
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=float(config.get("zoom", defaults["zoom"])),
        help="Initial map zoom level.",
    )
    parser.add_argument(
        "--nmea-history",
        dest="nmea_history",
        type=int,
        default=int(config.get("nmea_history", defaults["nmea_history"])),
        help="Number of recent NMEA sentences shown in the diagnostics panel.",
    )

    args = parser.parse_args(argv)
    # config_path is set by add_config_to_args
    return args


async def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for the GPS module."""
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("GPS module must be launched by the logger controller (commands disabled).")
        return

    # config_path is set by add_config_to_args in parse_args
    config_path = getattr(args, "config_path", None)
    defaults = GPSConfig()

    supervisor = StubCodexSupervisor(
        args,
        MODULE_DIR,
        logger.getChild("Supervisor"),
        runtime_factory=lambda context: GPSModuleRuntime(context),
        view_factory=GPSView,
        display_name=defaults.display_name,
        module_id=MODULE_ID,
        config_path=config_path,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(supervisor, loop)

    await supervisor.run()


if __name__ == "__main__":
    asyncio.run(main())
