"""VOG (Visual Occlusion Glasses) module entry point.

This module controls sVOG devices for visual occlusion experiments.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

MODULE_DIR = Path(__file__).resolve().parent


def _find_project_root(start: Path) -> Path:
    """Walk up until we locate the repository root (parent of rpi_logger package)."""
    for parent in start.parents:
        if parent.name == "rpi_logger":
            return parent.parent
    return start.parents[-1]


# Ensure the repository root (containing the rpi_logger package) is importable.
PROJECT_ROOT = _find_project_root(MODULE_DIR)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Re-use the stub VMC stack without copying its sources.
STUB_FRAMEWORK_DIR = MODULE_DIR.parent / "stub (codex)"
if STUB_FRAMEWORK_DIR.exists() and str(STUB_FRAMEWORK_DIR) not in sys.path:
    sys.path.insert(0, str(STUB_FRAMEWORK_DIR))

# Make sure any local virtual environment site-packages are available.
_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

# Add module dir so 'vog' package can be imported
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from vmc import StubCodexSupervisor
from vmc.constants import DISPLAY_NAME as STUB_DISPLAY_NAME

from vog.runtime import VOGModuleRuntime
from vog.view import VOGView
from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.VOG.vog_core.config.config_loader import load_config_file
from rpi_logger.modules.base.config_paths import resolve_module_config_path
from rpi_logger.cli.common import add_common_cli_arguments, install_signal_handlers

logger = get_module_logger("MainVOG")
CONFIG_CONTEXT = resolve_module_config_path(MODULE_DIR, "vog")


def parse_args(argv: Optional[list[str]] = None):
    """Parse command line arguments."""
    config = load_config_file(CONFIG_CONTEXT.writable_path)

    default_output = Path(config.get('output_dir', 'vog_data'))
    default_session_prefix = str(config.get('session_prefix', 'vog'))
    default_console = bool(config.get('console_output', False))

    parser = argparse.ArgumentParser(description="VOG (Visual Occlusion Glasses) module")

    # Use common CLI arguments for standard options
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=["gui", "headless"],
        default_mode=str(config.get('default_mode', 'gui')).lower(),
        include_session_prefix=True,
        default_session_prefix=default_session_prefix,
        include_console_control=True,
        default_console_output=default_console,
        include_auto_recording=False,  # VOG doesn't use auto-recording
        include_parent_control=True,
        include_window_geometry=True,
    )

    args = parser.parse_args(argv)
    args.config = config
    args.config_file_path = CONFIG_CONTEXT.writable_path
    return args


async def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for VOG module."""
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("VOG module must be launched by the logger controller (commands disabled).")
        return

    module_dir = Path(__file__).parent
    display_name = args.config.get('display_name', 'VOG')
    setattr(args, "config_path", CONFIG_CONTEXT.writable_path)

    supervisor = StubCodexSupervisor(
        args,
        module_dir,
        logger.getChild('Supervisor'),
        runtime_factory=lambda context: VOGModuleRuntime(context),
        view_factory=VOGView,
        display_name=display_name or STUB_DISPLAY_NAME,
        module_id="vog",
        config_path=CONFIG_CONTEXT.writable_path,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(supervisor, loop)

    await supervisor.run()


if __name__ == "__main__":
    asyncio.run(main())
