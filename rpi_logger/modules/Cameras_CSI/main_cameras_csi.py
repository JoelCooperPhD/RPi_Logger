"""Cameras_CSI module entry point using the stub (codex) stack.

Elm/Redux architecture optimized for AI interaction and full GUI testability.
"""

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
    __package__ = "rpi_logger.modules.Cameras_CSI"

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from vmc import StubCodexSupervisor, RuntimeRetryPolicy  # type: ignore  # noqa: E402
from rpi_logger.core.logging_utils import get_module_logger  # noqa: E402
from rpi_logger.modules.base.config_paths import (  # noqa: E402
    ModuleConfigContext,
    resolve_module_config_path,
)
from rpi_logger.cli.common import add_common_cli_arguments, add_config_to_args, install_signal_handlers  # noqa: E402
from .bridge import factory  # noqa: E402

DISPLAY_NAME = "Cameras-CSI"
MODULE_ID = "cameras_csi"

logger = get_module_logger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config-path", type=Path, default=None)
    pre_args, _ = pre_parser.parse_known_args(argv)

    if pre_args.config_path and pre_args.config_path.exists():
        config_ctx = ModuleConfigContext(
            module_id=MODULE_ID,
            template_path=MODULE_DIR / "config.txt",
            writable_path=pre_args.config_path,
            using_template=False,
        )
    else:
        config_ctx = resolve_module_config_path(MODULE_DIR, MODULE_ID, filename="config.txt")

    defaults = {
        "output_dir": "cameras_csi",
        "session_prefix": MODULE_ID,
        "console_output": False,
        "log_level": "info",
    }

    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")
    config = add_config_to_args(parser, config_ctx, defaults)

    add_common_cli_arguments(
        parser,
        default_output=Path(config.get("output_dir", defaults["output_dir"])),
        include_session_prefix=True,
        default_session_prefix=str(config.get("session_prefix", defaults["session_prefix"])),
        include_console_control=True,
        default_console_output=bool(config.get("console_output", defaults["console_output"])),
        include_auto_recording=True,
        include_parent_control=True,
        include_window_geometry=True,
    )

    parser.add_argument(
        "--camera-index",
        type=int,
        choices=[0, 1],
        default=None,
        help="CSI camera index for direct testing (0 or 1)",
    )

    return parser.parse_args(argv)


async def main_async(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    config_path = getattr(args, "config_path", None)

    supervisor = StubCodexSupervisor(
        args,
        module_dir=MODULE_DIR,
        logger=logger,
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
        runtime_factory=factory,
        runtime_retry_policy=RuntimeRetryPolicy(),
        config_path=config_path,
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
