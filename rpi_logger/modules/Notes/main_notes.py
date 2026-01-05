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
for path in [PROJECT_ROOT,
             MODULE_DIR.parent / "stub (codex)",
             PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"]:
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

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
logger = get_module_logger("MainNotes")


def parse_args(argv: Optional[list[str]] = None):
    config_ctx = resolve_module_config_path(MODULE_DIR, MODULE_ID)
    defaults = asdict(NotesConfig())
    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")
    config = add_config_to_args(parser, config_ctx, defaults)

    add_common_cli_arguments(
        parser,
        default_output=get_config_path(config, "output_dir", Path("notes")),
        include_session_prefix=True,
        default_session_prefix=get_config_str(config, "session_prefix", defaults["session_prefix"]),
        include_console_control=True,
        default_console_output=get_config_bool(config, "console_output", defaults["console_output"]),
        include_auto_recording=False,
        include_parent_control=True,
        include_window_geometry=True,
    )

    parser.add_argument("--history-limit", type=int,
                        default=get_config_int(config, "notes.history_limit", defaults["history_limit"]),
                        help="Maximum number of notes retained in the on-screen history")

    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument("--auto-start", dest="auto_start", action="store_true",
                            help="Automatically begin note collection when the module starts")
    auto_group.add_argument("--no-auto-start", dest="auto_start", action="store_false",
                            help="Disable automatic note collection on startup")
    parser.set_defaults(auto_start=get_config_bool(config, "notes.auto_start", defaults["auto_start"]))

    return parser.parse_args(argv)


def build_runtime(context):
    return NotesRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    if not args.enable_commands:
        logger.error("Notes module must be launched by the logger controller.")
        return

    def show_notes_help(parent):
        from rpi_logger.modules.Notes.help_dialog import NotesHelpDialog
        NotesHelpDialog(parent)

    supervisor = StubCodexSupervisor(
        args, MODULE_DIR, logger,
        runtime_factory=build_runtime,
        runtime_retry_policy=RuntimeRetryPolicy(interval=3.0, max_attempts=3),
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
        config_path=getattr(args, "config_path", None),
        help_callback=show_notes_help,
    )

    install_signal_handlers(supervisor, asyncio.get_running_loop())
    await supervisor.run()


if __name__ == "__main__":
    asyncio.run(main())
