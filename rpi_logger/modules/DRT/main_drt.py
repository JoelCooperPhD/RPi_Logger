"""DRT module entry point built on the shared stub VMC framework."""

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

from vmc import StubCodexSupervisor
from vmc.constants import DISPLAY_NAME as STUB_DISPLAY_NAME

from drt.runtime import DRTModuleRuntime
from drt.view import DRTView
from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.DRT.drt_core.config import load_config_file
from rpi_logger.modules.base.config_paths import resolve_module_config_path, resolve_writable_module_config
from rpi_logger.cli.common import install_signal_handlers

logger = get_module_logger("MainDRT")
CONFIG_CONTEXT = resolve_module_config_path(MODULE_DIR, "drt")


def parse_args(argv: Optional[list[str]] = None):
    config = load_config_file(CONFIG_CONTEXT.writable_path)

    default_output = Path(config.get('output_dir', 'drt_data'))
    default_session_prefix = str(config.get('session_prefix', 'drt'))
    default_console = bool(config.get('console_output', False))

    parser = argparse.ArgumentParser(description="DRT shell module")

    parser.add_argument(
        "--mode",
        choices=("gui", "headless"),
        default=str(config.get('default_mode', 'gui')).lower(),
        help="Execution mode supplied by the logger controller",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help="Session root provided by the module manager",
    )
    parser.add_argument(
        "--session-prefix",
        type=str,
        default=default_session_prefix,
        help="Prefix for generated session directories",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=str(config.get('log_level', 'info')),
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
        help="Enable stdin command channel (required when launched by the logger)",
    )
    parser.add_argument(
        "--window-geometry",
        type=str,
        default=None,
        help="Window layout forwarded when running with the GUI",
    )
    parser.add_argument(
        "--close-delay-ms",
        dest="close_delay_ms",
        type=int,
        default=0,
        help="Optional auto-close delay for placeholder windows (unused)",
    )

    console_group = parser.add_mutually_exclusive_group()
    console_group.add_argument(
        "--console",
        dest="console_output",
        action="store_true",
        help="Enable console logging",
    )
    console_group.add_argument(
        "--no-console",
        dest="console_output",
        action="store_false",
        help="Disable console logging",
    )
    parser.set_defaults(console_output=default_console)

    parser.add_argument(
        "--device-vid",
        type=lambda value: int(value, 0),
        default=int(config.get('device_vid', 0x239A)),
        help="USB vendor ID for the sDRT device",
    )
    parser.add_argument(
        "--device-pid",
        type=lambda value: int(value, 0),
        default=int(config.get('device_pid', 0x801E)),
        help="USB product ID for the sDRT device",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=int(config.get('baudrate', 9600)),
        help="Serial baudrate for the sDRT device",
    )

    args = parser.parse_args(argv)
    args.config = config
    args.config_file_path = CONFIG_CONTEXT.writable_path
    return args


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("DRT module must be launched by the logger controller (commands disabled).")
        return

    module_dir = Path(__file__).parent
    display_name = args.config.get('display_name', 'DRT')
    setattr(args, "config_path", CONFIG_CONTEXT.writable_path)

    supervisor = StubCodexSupervisor(
        args,
        module_dir,
        logger.getChild('Supervisor'),
        runtime_factory=lambda context: DRTModuleRuntime(context),
        view_factory=DRTView,
        display_name=display_name or STUB_DISPLAY_NAME,
        module_id="drt",
        config_path=CONFIG_CONTEXT.writable_path,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(supervisor, loop)

    await supervisor.run()


if __name__ == "__main__":
    asyncio.run(main())
