"""DRT module entry point built on the shared stub VMC framework."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

MODULE_DIR = Path(__file__).resolve().parent
MODULE_ID = "drt"


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

from rpi_logger.modules.DRT.drt.runtime import DRTModuleRuntime
from rpi_logger.modules.DRT.drt.view import DRTView
from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.DRT.config import DRTConfig
from rpi_logger.modules.base.config_paths import (
    ModuleConfigContext,
    resolve_module_config_path,
)
from rpi_logger.cli.common import add_common_cli_arguments, add_config_to_args, install_signal_handlers

logger = get_module_logger("MainDRT")


def parse_args(argv: Optional[list[str]] = None):
    # Pre-parse to get --config-path if provided by parent process (multi-instance)
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config-path", type=Path, default=None)
    pre_args, _ = pre_parser.parse_known_args(argv)

    # Use parent-provided path (instance-specific) or resolve normally (shared)
    if pre_args.config_path and pre_args.config_path.exists():
        config_ctx = ModuleConfigContext(
            module_id=MODULE_ID,
            template_path=MODULE_DIR / "config.txt",
            writable_path=pre_args.config_path,
            using_template=False,
        )
    else:
        config_ctx = resolve_module_config_path(MODULE_DIR, MODULE_ID)

    defaults = asdict(DRTConfig())

    parser = argparse.ArgumentParser(description="DRT shell module")
    config = add_config_to_args(parser, config_ctx, defaults)

    # Use common CLI arguments for standard options
    add_common_cli_arguments(
        parser,
        default_output=Path(config.get("output_dir", defaults["output_dir"])),
        include_session_prefix=True,
        default_session_prefix=str(config.get("session_prefix", defaults["session_prefix"])),
        include_console_control=True,
        default_console_output=bool(config.get("console_output", defaults["console_output"])),
        include_auto_recording=False,  # DRT doesn't use auto-recording
        include_parent_control=True,
        include_window_geometry=True,
    )

    # DRT-specific arguments only
    parser.add_argument(
        "--close-delay-ms",
        dest="close_delay_ms",
        type=int,
        default=0,
        help="Optional auto-close delay for placeholder windows (unused)",
    )
    parser.add_argument(
        "--device-vid",
        type=lambda value: int(value, 0),
        default=int(config.get("device_vid", defaults["device_vid"])),
        help="USB vendor ID for the DRT device",
    )
    parser.add_argument(
        "--device-pid",
        type=lambda value: int(value, 0),
        default=int(config.get("device_pid", defaults["device_pid"])),
        help="USB product ID for the DRT device",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=int(config.get("baudrate", defaults["baudrate"])),
        help="Serial baudrate for the DRT device",
    )

    return parser.parse_args(argv)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("DRT module must be launched by the logger controller (commands disabled).")
        return

    defaults = DRTConfig()
    config_path = getattr(args, "config_path", None)

    supervisor = StubCodexSupervisor(
        args,
        MODULE_DIR,
        logger.getChild("Supervisor"),
        runtime_factory=lambda context: DRTModuleRuntime(context),
        view_factory=DRTView,
        display_name=defaults.display_name or STUB_DISPLAY_NAME,
        module_id=MODULE_ID,
        config_path=config_path,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(supervisor, loop)

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
