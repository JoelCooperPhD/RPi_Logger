import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cli_utils import (
    add_common_cli_arguments,
    setup_module_logging,
    install_exception_handlers,
    install_signal_handlers,
    log_module_startup,
    log_module_shutdown,
)
from Modules.base import load_window_geometry_from_config
from stub_core import MODULE_NAME, MODULE_DESCRIPTION
from stub_core.config import load_config_file_async
from stub_core.stub_supervisor import StubSupervisor

logger = logging.getLogger(__name__)


async def parse_args_async(argv: Optional[list[str]] = None):
    config_path = Path(__file__).parent / "config.txt"
    config = await load_config_file_async(config_path)

    parser = argparse.ArgumentParser(description=f"{MODULE_NAME} - {MODULE_DESCRIPTION}")

    add_common_cli_arguments(
        parser,
        default_output=Path("stub_data"),
        allowed_modes=["gui", "headless"],
        default_mode="gui",
        default_session_prefix="stub",
        default_console_output=False,
        default_auto_start_recording=False,
    )

    args = parser.parse_args(argv)
    args.window_geometry = load_window_geometry_from_config(config, args.window_geometry)
    args.config = config
    args.config_file_path = config_path

    return args


async def main():
    args = await parse_args_async()

    module_dir = Path(__file__).parent
    session_name, log_file, is_command_mode = setup_module_logging(
        args,
        module_name='stub',
        module_dir=module_dir,
        default_prefix='stub'
    )

    log_module_startup(
        logger,
        session_name,
        log_file,
        args,
        module_name="stub",
    )

    supervisor = StubSupervisor(args)
    loop = asyncio.get_running_loop()

    install_exception_handlers(logger, loop)
    install_signal_handlers(supervisor, loop, track_shutdown_state=True)

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()
        log_module_shutdown(logger, "stub")


if __name__ == "__main__":
    asyncio.run(main())
