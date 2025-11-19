"""stub (codex) shell module entry point built on a VMC architecture."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

_venv_site = Path(__file__).parent.parent.parent / '.venv' / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from rpi_logger.core.logging_utils import get_module_logger
from vmc import StubCodexSupervisor
from vmc.constants import DEFAULT_OUTPUT_SUBDIR, DISPLAY_NAME

logger = get_module_logger(__name__)



def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} shell module")

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
        default="stub_codex",
        help="Prefix for generated session directories",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        help="Logging verbosity",
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
        help="Flag supplied by the logger when running autonomously",
    )
    parser.add_argument(
        "--window-geometry",
        type=str,
        default=None,
        help="Window layout forwarded when running with the GUI",
    )
    parser.add_argument(
        "--close-delay-ms",
        dest="close_delay_ms",
        type=int,
        default=0,
        help="Optional auto-close delay for the placeholder window (0 keeps it open until disabled)",
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


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("Shell stub module must be launched by the logger controller.")
        return

    module_dir = Path(__file__).parent

    supervisor = StubCodexSupervisor(args, module_dir, logger)

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
