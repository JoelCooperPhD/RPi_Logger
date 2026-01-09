"""Cameras_USB module entry point.

USB camera module with optional audio recording, using Elm/Redux architecture.
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
    __package__ = "rpi_logger.modules.Cameras_USB"

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

try:
    from vmc import StubCodexSupervisor, RuntimeRetryPolicy
except ImportError:
    StubCodexSupervisor = None
    RuntimeRetryPolicy = None

try:
    from rpi_logger.core.logging_utils import get_module_logger
except ImportError:
    import logging
    def get_module_logger(name):
        return logging.getLogger(name)

try:
    from rpi_logger.modules.base.config_paths import (
        ModuleConfigContext,
        resolve_module_config_path,
    )
except ImportError:
    ModuleConfigContext = None
    resolve_module_config_path = None

try:
    from rpi_logger.cli.common import add_common_cli_arguments, add_config_to_args, install_signal_handlers
except ImportError:
    add_common_cli_arguments = None
    add_config_to_args = None
    install_signal_handlers = None

from .bridge import factory

DISPLAY_NAME = "Cameras-USB"
MODULE_ID = "cameras_usb"

logger = get_module_logger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config-path", type=Path, default=None)
    pre_args, _ = pre_parser.parse_known_args(argv)

    config_ctx = None
    if resolve_module_config_path:
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
        "output_dir": "cameras_usb",
        "session_prefix": MODULE_ID,
        "console_output": False,
        "log_level": "info",
        "audio_mode": "auto",
    }

    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")

    config = {}
    if config_ctx and add_config_to_args:
        config = add_config_to_args(parser, config_ctx, defaults)

    if add_common_cli_arguments:
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
        "--device",
        type=str,
        default=None,
        help="USB camera device path (e.g., /dev/video0)",
    )

    parser.add_argument(
        "--audio",
        type=str,
        choices=["auto", "on", "off"],
        default="auto",
        help="Audio recording mode (default: auto)",
    )

    parser.add_argument(
        "--audio-device",
        type=str,
        default=None,
        help="Specific audio device (default: auto-detect)",
    )

    parser.add_argument(
        "--container",
        type=str,
        choices=["mp4", "mkv", "avi"],
        default="mp4",
        help="Output container format (default: mp4)",
    )

    return parser.parse_args(argv)


async def main_async(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    config_path = getattr(args, "config_path", None)

    if StubCodexSupervisor:
        supervisor = StubCodexSupervisor(
            args,
            module_dir=MODULE_DIR,
            logger=logger,
            display_name=DISPLAY_NAME,
            module_id=MODULE_ID,
            runtime_factory=factory,
            runtime_retry_policy=RuntimeRetryPolicy() if RuntimeRetryPolicy else None,
            config_path=config_path,
        )

        loop = asyncio.get_running_loop()
        if install_signal_handlers:
            install_signal_handlers(supervisor, loop)

        try:
            await supervisor.run()
        finally:
            await supervisor.shutdown()
    else:
        logger.info("Running in standalone mode (no StubCodexSupervisor)")
        from .bridge import USBCamerasRuntime

        class SimpleContext:
            def __init__(self):
                self.args = args
                self.logger = logger
                self.module_dir = MODULE_DIR
                self.view = None
                self.model = None

        ctx = SimpleContext()
        runtime = USBCamerasRuntime(ctx)
        await runtime.start()

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await runtime.shutdown()


def main(argv: Optional[list[str]] = None) -> None:
    asyncio.run(main_async(argv))


if __name__ == "__main__":
    main()
