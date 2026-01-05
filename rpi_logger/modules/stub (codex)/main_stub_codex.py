"""stub (codex) shell module entry point built on a VMC architecture."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

_venv_site = Path(__file__).parent.parent.parent / '.venv' / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.cli.common import add_common_cli_arguments
from vmc import StubCodexSupervisor
from vmc.constants import DEFAULT_OUTPUT_SUBDIR, DISPLAY_NAME

logger = get_module_logger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} shell module")

    # Use common CLI arguments for standard options
    add_common_cli_arguments(
        parser,
        default_output=DEFAULT_OUTPUT_SUBDIR,
        include_session_prefix=True,
        default_session_prefix="stub_codex",
        include_console_control=True,
        default_console_output=False,
        include_auto_recording=False,  # Stub doesn't use auto-recording
        include_parent_control=True,
        include_window_geometry=True,
    )

    # Stub-specific arguments only
    parser.add_argument(
        "--close-delay-ms",
        dest="close_delay_ms",
        type=int,
        default=0,
        help="Optional auto-close delay for the placeholder window (0 keeps it open until disabled)",
    )

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
