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
from rpi_logger.cli.common import add_common_cli_arguments, install_signal_handlers

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

    # Use common CLI arguments for standard options
    add_common_cli_arguments(
        parser,
        default_output=_config_path(config, "output_dir", DEFAULT_OUTPUT_SUBDIR),
        allowed_modes=["gui", "headless"],
        default_mode=_normalize_mode(_config_text(config, "mode") or "gui"),
        include_session_prefix=True,
        default_session_prefix=_config_text(config, "session_prefix") or MODULE_ID,
        include_console_control=True,
        default_console_output=_config_bool(config, "console_output", False),
        include_auto_recording=False,  # Notes uses its own --auto-start terminology
        include_parent_control=True,
        include_window_geometry=True,
    )

    # Notes-specific arguments
    parser.add_argument(
        "--history-limit",
        type=int,
        default=_config_int(config, "history_limit", DEFAULT_HISTORY_LIMIT),
        help="Maximum number of notes retained in the on-screen history",
    )

    # Notes-specific auto-start (different from generic "recording")
    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument(
        "--auto-start",
        dest="auto_start",
        action="store_true",
        help="Automatically begin note collection when the module starts",
    )
    auto_group.add_argument(
        "--no-auto-start",
        dest="auto_start",
        action="store_false",
        help="Disable automatic note collection on startup",
    )
    parser.set_defaults(auto_start=_config_bool(config, "auto_start", False))

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

    await supervisor.run()


if __name__ == "__main__":
    asyncio.run(main())
