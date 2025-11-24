"""Cameras module entry point leveraging the stub (codex) stack."""

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
    __package__ = "rpi_logger.modules.Cameras"

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from vmc import StubCodexSupervisor, RuntimeRetryPolicy  # type: ignore  # noqa: E402
from vmc.constants import PLACEHOLDER_GEOMETRY  # type: ignore  # noqa: E402
from rpi_logger.core.logging_utils import get_module_logger  # noqa: E402
from rpi_logger.modules.base.config_paths import resolve_module_config_path  # noqa: E402
from rpi_logger.cli.common import install_signal_handlers  # noqa: E402
from .bridge import factory  # noqa: E402

DISPLAY_NAME = "Cameras"
MODULE_ID = "cameras"
DEFAULT_OUTPUT_SUBDIR = Path("cameras")

logger = get_module_logger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")
    parser.add_argument("--mode", choices=("gui", "headless"), default="gui")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_SUBDIR)
    parser.add_argument("--session-prefix", type=str, default=MODULE_ID)
    parser.add_argument("--log-level", type=str, default="info")
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--enable-commands", action="store_true", default=False)
    parser.add_argument("--window-geometry", type=str, default=None)

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


async def main_async(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    config_ctx = resolve_module_config_path(MODULE_DIR, MODULE_ID, filename="config.txt")

    supervisor = StubCodexSupervisor(
        args,
        module_dir=MODULE_DIR,
        logger=logger,
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
        runtime_factory=factory,
        runtime_retry_policy=RuntimeRetryPolicy(),
        config_path=config_ctx.writable_path,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(supervisor, loop)

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


def main(argv: Optional[list[str]] = None) -> None:
    asyncio.run(main_async(argv))


if __name__ == "__main__":
    main()
