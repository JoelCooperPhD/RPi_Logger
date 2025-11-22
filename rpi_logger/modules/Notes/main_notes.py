"""Notes module entry point leveraging the Codex VMC stack."""

from __future__ import annotations

import argparse
import asyncio
from rpi_logger.core.logging_utils import get_module_logger
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

from vmc import StubCodexSupervisor, RuntimeRetryPolicy
from vmc.constants import PLACEHOLDER_GEOMETRY

from notes_runtime import NotesRuntime
from rpi_logger.modules.base.config_paths import resolve_module_config_path, resolve_writable_module_config
from rpi_logger.modules.base.preferences import ModulePreferences
from rpi_logger.cli.common import install_signal_handlers

DISPLAY_NAME = "Notes"
MODULE_ID = "notes"
DEFAULT_OUTPUT_SUBDIR = Path("notes")
DEFAULT_HISTORY_LIMIT = 200
CONFIG_PATH = resolve_writable_module_config(MODULE_DIR, MODULE_ID)
PREFERENCES = ModulePreferences(CONFIG_PATH)

logger = get_module_logger("MainNotes")


def parse_args(argv: Optional[list[str]] = None):
    config = _load_notes_config()
    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")

    parser.add_argument(
        "--mode",
        choices=("gui", "headless"),
        default=_normalize_mode(_config_text(config, "mode") or "gui"),
        help="Execution mode set by the module manager",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_config_path(config, "output_dir", DEFAULT_OUTPUT_SUBDIR),
        help="Session root provided by the module manager",
    )
    parser.add_argument(
        "--session-prefix",
        type=str,
        default=_config_text(config, "session_prefix") or MODULE_ID,
        help="Prefix for generated session directories",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=_config_text(config, "log_level") or "info",
        help="Logging verbosity",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=_config_optional_path(config, "log_file"),
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
        default=_config_int(config, "history_limit", DEFAULT_HISTORY_LIMIT),
        help="Maximum number of notes retained in the on-screen history",
    )

    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument(
        "--auto-start",
        dest="auto_start",
        action="store_true",
        help="Automatically begin recording when the module starts",
    )
    auto_group.add_argument(
        "--no-auto-start",
        dest="auto_start",
        action="store_false",
        help="Disable automatic recording on startup",
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
        help="Disable console logging",
    )

    parser.set_defaults(
        auto_start=_config_bool(config, "auto_start", False),
        console_output=_config_bool(config, "console_output", False),
    )

    return parser.parse_args(argv)


def build_runtime(context):
    return NotesRuntime(context)


def _load_notes_config() -> dict[str, str]:
    return PREFERENCES.snapshot()


def _config_text(config: dict[str, str], key: str) -> Optional[str]:
    raw = config.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _config_bool(config: dict[str, str], key: str, default: bool) -> bool:
    text = _config_text(config, key)
    if text is None:
        return default
    lowered = text.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _config_int(config: dict[str, str], key: str, default: int) -> int:
    text = _config_text(config, key)
    if text is None:
        return default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _config_path(config: dict[str, str], key: str, default: Path) -> Path:
    text = _config_text(config, key)
    if text is None:
        return default
    try:
        return Path(text)
    except Exception:
        return default


def _config_optional_path(config: dict[str, str], key: str) -> Optional[Path]:
    text = _config_text(config, key)
    if text is None:
        return None
    try:
        return Path(text)
    except Exception:
        return None


def _normalize_mode(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"headless", "cli"}:
        return "headless"
    return "gui"


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("Notes module must be launched by the logger controller.")
        return

    module_dir = MODULE_DIR

    config_context = resolve_module_config_path(MODULE_DIR, MODULE_ID)
    setattr(args, "config_path", config_context.writable_path)

    supervisor = StubCodexSupervisor(
        args,
        module_dir,
        logger,
        runtime_factory=build_runtime,
        runtime_retry_policy=RuntimeRetryPolicy(interval=3.0, max_attempts=3),
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
