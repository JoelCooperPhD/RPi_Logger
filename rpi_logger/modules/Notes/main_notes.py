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

from dataclasses import asdict

from vmc import StubCodexSupervisor, RuntimeRetryPolicy

from notes_runtime import NotesRuntime
from rpi_logger.modules.base.config_paths import resolve_module_config_path
from rpi_logger.cli.common import (
    add_common_cli_arguments,
    add_config_to_args,
    install_signal_handlers,
    get_config_bool,
    get_config_int,
    get_config_str,
    get_config_path,
)

from rpi_logger.modules.Notes.config import NotesConfig

DISPLAY_NAME = "Notes"
MODULE_ID = "notes"
DEFAULT_OUTPUT_SUBDIR = Path("notes")
DEFAULT_HISTORY_LIMIT = 200

logger = get_module_logger("MainNotes")


def parse_args(argv: Optional[list[str]] = None):
    config_ctx = resolve_module_config_path(MODULE_DIR, MODULE_ID)
    defaults = asdict(NotesConfig())

    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")

    # Load config using unified helper
    config = add_config_to_args(parser, config_ctx, defaults)

    # Use common CLI arguments for standard options
    add_common_cli_arguments(
        parser,
        default_output=get_config_path(config, "output_dir", DEFAULT_OUTPUT_SUBDIR),
        allowed_modes=["gui", "headless"],
        default_mode=_normalize_mode(get_config_str(config, "mode", defaults["mode"])),
        include_session_prefix=True,
        default_session_prefix=get_config_str(config, "session_prefix", defaults["session_prefix"]),
        include_console_control=True,
        default_console_output=get_config_bool(config, "console_output", defaults["console_output"]),
        include_auto_recording=False,  # Notes uses its own --auto-start terminology
        include_parent_control=True,
        include_window_geometry=True,
    )

    # Notes-specific arguments
    parser.add_argument(
        "--history-limit",
        type=int,
        default=get_config_int(config, "notes.history_limit", defaults["history_limit"]),
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
    parser.set_defaults(auto_start=get_config_bool(config, "notes.auto_start", defaults["auto_start"]))

    args = parser.parse_args(argv)
    # config_path is set by add_config_to_args
    return args


def build_runtime(context):
    return NotesRuntime(context)


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

    # config_path is set by add_config_to_args in parse_args
    config_path = getattr(args, "config_path", None)

    def show_notes_help(parent):
        from rpi_logger.modules.Notes.help_dialog import NotesHelpDialog
        NotesHelpDialog(parent)

    supervisor = StubCodexSupervisor(
        args,
        MODULE_DIR,
        logger,
        runtime_factory=build_runtime,
        runtime_retry_policy=RuntimeRetryPolicy(interval=3.0, max_attempts=3),
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
        config_path=config_path,
        help_callback=show_notes_help,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(supervisor, loop)

    await supervisor.run()


if __name__ == "__main__":
    asyncio.run(main())
