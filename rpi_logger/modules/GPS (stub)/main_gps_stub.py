"""GPS (stub) module entry point leveraging the stub (codex) architecture."""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
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
    get_config_bool,
    get_config_float,
    get_config_int,
    get_config_str,
    positive_float,
)
from rpi_logger.core.config_manager import get_config_manager
from vmc import StubCodexSupervisor, RuntimeRetryPolicy

from gps_runtime import GPSStubRuntime

DISPLAY_NAME = "GPS (Stub)"
MODULE_ID = "gps_stub"
DEFAULT_OUTPUT_SUBDIR = Path("gps-stub")

logger = logging.getLogger(__name__)


def _load_config(config_path: Path) -> dict:
    manager = get_config_manager()
    try:
        return manager.read_config(config_path)
    except Exception:
        return {}


def _resolve_offline_tiles_path(raw_value: Optional[str], module_dir: Path) -> Optional[Path]:
    if not raw_value:
        return None

    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = (module_dir / candidate).resolve()

    if candidate.exists():
        return candidate

    legacy = (module_dir.parent / "GPS" / "offline_tiles.db").resolve()
    if legacy.exists():
        target = module_dir / "offline_tiles.db"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            should_copy = not target.exists() or legacy.stat().st_mtime > target.stat().st_mtime
        except OSError:
            should_copy = False

        if should_copy:
            try:
                shutil.copy2(legacy, target)
                logger.info("Copied offline tiles database from %s to %s", legacy, target)
                return target
            except Exception as exc:
                logger.warning("Failed to copy offline tiles DB (%s); falling back to legacy path", exc)
                return legacy
        return target

    logger.info("Offline tiles file %s not found; online tiles will be used", candidate)
    return None


def parse_args(argv: Optional[list[str]] = None):
    config_path = MODULE_DIR / "config.txt"
    config = _load_config(config_path)

    default_output = Path(get_config_str(config, "output_dir", str(DEFAULT_OUTPUT_SUBDIR)))
    default_session_prefix = get_config_str(config, "session_prefix", MODULE_ID)
    default_console = get_config_bool(config, "console_output", False)
    default_auto_start = get_config_bool(config, "auto_start_recording", False)

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
        "--serial-port",
        type=str,
        default=get_config_str(config, "serial_port", "/dev/serial0"),
        help="Serial device path for the GPS receiver",
    )
    parser.add_argument(
        "--baud-rate",
        dest="baud_rate",
        type=int,
        default=get_config_int(config, "baud_rate", 9600),
        help="Serial baud rate for GPS communication",
    )
    parser.add_argument(
        "--device-timeout",
        dest="device_timeout",
        type=positive_float,
        default=get_config_float(config, "device_timeout", 10.0),
        help="Maximum seconds to search for the GPS receiver",
    )
    parser.add_argument(
        "--discovery-retry",
        dest="discovery_retry",
        type=positive_float,
        default=get_config_float(config, "discovery_retry", 3.0),
        help="Seconds between discovery attempts",
    )
    parser.add_argument(
        "--gps-update-hz",
        dest="gps_update_hz",
        type=positive_float,
        default=get_config_float(config, "gps_update_hz", 10.0),
        help="Frequency of GPS UI updates",
    )

    parser.add_argument(
        "--map-zoom",
        dest="map_zoom",
        type=positive_float,
        default=get_config_float(config, "map_zoom", 11.0),
        help="Default map zoom level",
    )
    parser.add_argument(
        "--map-center",
        dest="map_center",
        type=str,
        default=f"{get_config_float(config, 'map_center_lat', 40.7608)},{get_config_float(config, 'map_center_lon', -111.8910)}",
        help="Map center lat,lon pair",
    )

    parser.add_argument(
        "--offline-tiles",
        dest="offline_tiles",
        type=str,
        default=get_config_str(config, "offline_tiles", "offline_tiles.db"),
        help="Path to an optional SQLite offline tiles DB",
    )

    args = parser.parse_args(argv)

    default_lat = get_config_float(config, "map_center_lat", 40.7608)
    default_lon = get_config_float(config, "map_center_lon", -111.8910)
    try:
        lat_str, lon_str = str(args.map_center).split(",", 1)
        args.map_center = (float(lat_str.strip()), float(lon_str.strip()))
    except Exception:
        args.map_center = (default_lat, default_lon)

    args.offline_tiles = _resolve_offline_tiles_path(args.offline_tiles, MODULE_DIR)

    args.config = config
    args.config_file_path = config_path

    return args


def build_runtime(context):
    return GPSStubRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not getattr(args, "enable_commands", False):
        logger.error("GPS (stub) module must be launched by the logger controller.")
        return

    supervisor = StubCodexSupervisor(
        args,
        MODULE_DIR,
        logger,
        runtime_factory=build_runtime,
        runtime_retry_policy=RuntimeRetryPolicy(interval=3.0, max_attempts=None),
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
    )

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
