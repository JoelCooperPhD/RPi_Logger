"""Audio module entry point leveraging the codex stack."""

from __future__ import annotations

import asyncio
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
from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.Audio.config import AudioSettings, parse_cli_args
from rpi_logger.modules.base.config_paths import resolve_module_config_path, resolve_writable_module_config
from rpi_logger.modules.Audio.runtime import AudioRuntime
from rpi_logger.cli.common import install_signal_handlers

DISPLAY_NAME = "Audio"
MODULE_ID = "audio"
CONFIG_PATH = resolve_writable_module_config(MODULE_DIR, MODULE_ID)

logger = get_module_logger("Audio")

_DEFAULT_LOG_LEVEL = AudioSettings().log_level.lower()
_LEVEL_ALIASES = {
    "warn": "warning",
    "fatal": "critical",
    "err": "error",
}
_VALID_LOG_LEVELS = {"debug", "info", "warning", "error", "critical"}


def _resolve_log_level(value: str | None) -> tuple[str, bool]:
    """Normalize user-supplied log levels before configuring logging."""

    normalized = (value or "").strip().lower()
    if not normalized:
        return _DEFAULT_LOG_LEVEL, False
    normalized = _LEVEL_ALIASES.get(normalized, normalized)
    if normalized in _VALID_LOG_LEVELS:
        return normalized, False
    return _DEFAULT_LOG_LEVEL, True

def parse_args(argv: Optional[list[str]] = None):
    return parse_cli_args(argv, config_path=CONFIG_PATH)


def build_runtime(context):
    return AudioRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    requested_level = str(getattr(args, "log_level", "") or "")
    effective_level, invalid_level = _resolve_log_level(requested_level)
    configure_logging(
        level=effective_level,
        console=getattr(args, "console_output", True),
        log_file=getattr(args, "log_file", None),
    )
    if requested_level and invalid_level:
        logger.warning(
            "Unknown log level '%s'; defaulting to %s",
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

    config_context = resolve_module_config_path(module_dir, MODULE_ID)
    setattr(args, "config_path", config_context.writable_path)

    supervisor = StubCodexSupervisor(
        args,
        module_dir,
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
