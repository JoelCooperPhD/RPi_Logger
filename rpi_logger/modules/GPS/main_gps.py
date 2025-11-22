"""GPS module that renders the offline map inside the stub view."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

from rpi_logger.cli.common import add_common_cli_arguments, install_signal_handlers  # noqa: E402
from rpi_logger.core.logging_utils import get_module_logger  # noqa: E402
from vmc import StubCodexSupervisor  # noqa: E402

from runtime import GPSPreviewRuntime  # noqa: E402
from rpi_logger.modules.base.config_paths import resolve_module_config_path

DISPLAY_NAME = "GPS"
MODULE_ID = "gps"
DEFAULT_OUTPUT_SUBDIR = Path("gps")
DEFAULT_CENTER = (40.7608, -111.8910)
DEFAULT_ZOOM = 13.0
DEFAULT_OFFLINE_DB = (MODULE_DIR / "offline_tiles.db").resolve()
DEFAULT_SERIAL_PORT = "/dev/serial0"
DEFAULT_BAUD_RATE = 9600
DEFAULT_RECONNECT_DELAY = 3.0
DEFAULT_NMEA_HISTORY = 30

logger = get_module_logger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} preview module")
    add_common_cli_arguments(
        parser,
        default_output=DEFAULT_OUTPUT_SUBDIR,
        allowed_modes=("gui", "headless"),
        default_mode="gui",
        default_session_prefix=MODULE_ID,
        default_console_output=False,
        default_auto_start_recording=False,
    )

    parser.add_argument(
        "--offline-db",
        dest="offline_db",
        type=Path,
        default=DEFAULT_OFFLINE_DB,
        help="Path to the offline tiles database (defaults to the main GPS cache).",
    )
    parser.add_argument(
        "--center-lat",
        type=float,
        default=DEFAULT_CENTER[0],
        help="Initial map latitude.",
    )
    parser.add_argument(
        "--center-lon",
        type=float,
        default=DEFAULT_CENTER[1],
        help="Initial map longitude.",
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=DEFAULT_ZOOM,
        help="Initial map zoom level.",
    )
    parser.add_argument(
        "--serial-port",
        dest="serial_port",
        type=str,
        default=DEFAULT_SERIAL_PORT,
        help="Serial device that BerryGPS is wired to (defaults to /dev/serial0).",
    )
    parser.add_argument(
        "--baud-rate",
        dest="baud_rate",
        type=int,
        default=DEFAULT_BAUD_RATE,
        help="Serial baud rate used by BerryGPS (9600 by default).",
    )
    parser.add_argument(
        "--reconnect-delay",
        dest="reconnect_delay",
        type=float,
        default=DEFAULT_RECONNECT_DELAY,
        help="Seconds to wait before attempting to reopen the GPS device after a failure.",
    )
    parser.add_argument(
        "--nmea-history",
        dest="nmea_history",
        type=int,
        default=DEFAULT_NMEA_HISTORY,
        help="Number of recent NMEA sentences shown in the diagnostics panel.",
    )
    return parser.parse_args(argv)


def build_runtime(context):
    return GPSPreviewRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not getattr(args, "enable_commands", False):
        logger.error("GPS module must be launched by the logger controller.")
        return

    config_context = resolve_module_config_path(MODULE_DIR, MODULE_ID)
    setattr(args, "config_path", config_context.writable_path)

    supervisor = StubCodexSupervisor(
        args,
        MODULE_DIR,
        logger,
        runtime_factory=build_runtime,
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
        config_path=config_context.writable_path,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(supervisor, loop)

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
