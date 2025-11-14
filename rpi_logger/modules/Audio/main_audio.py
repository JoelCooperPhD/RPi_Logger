"""Audio module entry point leveraging the codex stack."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import sys
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

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from vmc import StubCodexSupervisor

from rpi_logger.core.logging_config import configure_logging
from rpi_logger.modules.Audio.config import parse_cli_args
from rpi_logger.modules.base.config_paths import resolve_writable_module_config
from rpi_logger.modules.Audio.runtime import AudioRuntime

DISPLAY_NAME = "Audio"
MODULE_ID = "audio"
CONFIG_PATH = resolve_writable_module_config(MODULE_DIR, MODULE_ID)

logger = logging.getLogger("Audio")

def parse_args(argv: Optional[list[str]] = None):
    return parse_cli_args(argv, config_path=CONFIG_PATH)


def build_runtime(context):
    return AudioRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    requested_level = str(getattr(args, "log_level", "") or "").lower()
    effective_level = "debug"
    configure_logging(
        level=effective_level,
        console=getattr(args, "console_output", True),
        log_file=getattr(args, "log_file", None),
    )
    if requested_level and requested_level != effective_level:
        logger.warning(
            "Ignoring requested log level '%s'; forcing %s for Audio",
            requested_level,
            effective_level,
        )
    logger.debug(
        "Audio entry configured (console=%s, log_file=%s)",
        getattr(args, "console_output", True),
        getattr(args, "log_file", None),
    )

    if not args.enable_commands:
        logger.error("Audio module must be launched by the logger controller.")
        return

    module_dir = MODULE_DIR

    supervisor = StubCodexSupervisor(
        args,
        module_dir,
        logger,
        runtime_factory=build_runtime,
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
    )

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
