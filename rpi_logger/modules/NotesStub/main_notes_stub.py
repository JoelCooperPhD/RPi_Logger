"""Notes stub module entry point leveraging the stub (codex) VMC stack."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys
from typing import Optional

MODULE_DIR = Path(__file__).parent
PROJECT_ROOT = MODULE_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from vmc import StubCodexSupervisor, RuntimeRetryPolicy
from vmc.constants import PLACEHOLDER_GEOMETRY

from notes_runtime import NotesStubRuntime

DISPLAY_NAME = "Notes (Stub)"
MODULE_ID = "notes_stub"
DEFAULT_OUTPUT_SUBDIR = Path("notes-stub")
DEFAULT_HISTORY_LIMIT = 200

logger = logging.getLogger(__name__)


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
        "--history-limit",
        type=int,
        default=DEFAULT_HISTORY_LIMIT,
        help="Maximum number of notes retained in the on-screen history",
    )
    parser.add_argument(
        "--auto-start",
        action="store_true",
        default=False,
        help="Automatically begin recording when the module starts",
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
    return NotesStubRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("Notes stub module must be launched by the logger controller.")
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
