"""Cameras module entry point leveraging the stub (codex) VMC stack."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
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
    __package__ = "rpi_logger.modules.Cameras"

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from vmc import StubCodexSupervisor, RuntimeRetryPolicy
from vmc.constants import PLACEHOLDER_GEOMETRY

from rpi_logger.core.logging_utils import get_module_logger
from .camera_runtime import CamerasRuntime

DISPLAY_NAME = "Cameras"
MODULE_ID = "cameras"
DEFAULT_OUTPUT_SUBDIR = Path("cameras")

logger = get_module_logger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")

    parser.add_argument(
        "--mode",
        choices=("gui", "headless"),
        default="gui",
        help="Execution mode set by the module manager",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_SUBDIR,
        help="Session root provided by the module manager",
    )
    parser.add_argument(
        "--session-prefix",
        type=str,
        default=MODULE_ID,
        help="Prefix for generated session directories",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="debug",
        help="Logging verbosity (default: debug)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional explicit log file path",
    )
    parser.add_argument(
        "--enable-commands",
        action="store_true",
        default=False,
        help="Flag supplied by the logger when running under module manager",
    )
    parser.add_argument(
        "--window-geometry",
        type=str,
        default=None,
        help=(
            "Initial window geometry when launched with GUI "
            f"(fallback to saved config or {PLACEHOLDER_GEOMETRY})"
        ),
    )
    parser.add_argument(
        "--preview-width",
        type=int,
        default=640,
        help="Preview width in pixels (default: 640)",
    )
    parser.add_argument(
        "--preview-height",
        type=int,
        default=480,
        help="Preview height in pixels (default: 480)",
    )
    parser.add_argument(
        "--preview-interval",
        type=float,
        default=0.2,
        help="Seconds between preview frame updates",
    )
    parser.add_argument(
        "--preview-fps",
        type=float,
        default=None,
        help="Optional preview FPS cap (overrides --preview-interval when provided)",
    )
    parser.add_argument(
        "--max-cameras",
        type=int,
        default=2,
        help="Maximum number of cameras to preview",
    )
    parser.add_argument(
        "--capture-width",
        type=int,
        default=None,
        help="Main stream width in pixels (default: sensor native)",
    )
    parser.add_argument(
        "--capture-height",
        type=int,
        default=None,
        help="Main stream height in pixels (default: sensor native)",
    )
    parser.add_argument(
        "--save-images",
        action="store_true",
        default=False,
        help="Enable saving frames to disk",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=None,
        help="Directory for saved frames (default: <output-dir>/captures)",
    )
    parser.add_argument(
        "--save-width",
        type=int,
        default=None,
        help="Optional width to downsample saved frames",
    )
    parser.add_argument(
        "--save-height",
        type=int,
        default=None,
        help="Optional height to downsample saved frames",
    )
    parser.add_argument(
        "--save-fps",
        type=float,
        default=None,
        help="Maximum FPS for saved frames (default: unlimited)",
    )
    parser.add_argument(
        "--save-format",
        type=str,
        default="jpeg",
        help="Image format for saved frames (jpeg|png|webp)",
    )
    parser.add_argument(
        "--save-quality",
        type=int,
        default=90,
        help="Quality for saved JPEG frames (1-100)",
    )
    parser.add_argument(
        "--session-retention",
        type=int,
        default=5,
        help="Number of recording sessions to retain per output directory (older sessions are pruned)",
    )
    parser.add_argument(
        "--min-free-space-mb",
        type=int,
        default=512,
        help="Minimum free space (in MB) required before recording can start",
    )
    parser.add_argument(
        "--storage-queue-size",
        type=int,
        default=8,
        help="Maximum number of frames buffered per camera before storage (prevents silent drops)",
    )

    console_group = parser.add_mutually_exclusive_group()
    console_group.add_argument(
        "--console",
        dest="console_output",
        action="store_true",
        help="Enable console logging (unused for manager launches)",
    )
    console_group.add_argument(
        "--no-console",
        dest="console_output",
        action="store_false",
        help="Disable console logging (default)",
    )
    parser.set_defaults(console_output=False)

    return parser.parse_args(argv)


def build_runtime(context):
    return CamerasRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("Cameras module must be launched by the logger controller.")
        return

    module_dir = MODULE_DIR

    supervisor = StubCodexSupervisor(
        args,
        module_dir,
        logger,
        runtime_factory=build_runtime,
        runtime_retry_policy=RuntimeRetryPolicy(interval=3.0, max_attempts=3),
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
    )

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
