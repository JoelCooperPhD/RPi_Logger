import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rpi_logger.cli.common import (
    add_common_cli_arguments,
    ensure_directory,
    get_config_str,
    get_config_bool,
    get_config_int,
    setup_module_logging,
    install_exception_handlers,
    install_signal_handlers,
    log_module_startup,
    log_module_shutdown,
)
from rpi_logger.modules.base import load_window_geometry_from_config
from drt_core import MODULE_NAME, MODULE_DESCRIPTION
from drt_core.config import load_config_file
from drt_core.drt_supervisor import DRTSupervisor

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    config_path = Path(__file__).parent / "config.txt"
    config = load_config_file(config_path)

    default_output = Path(get_config_str(config, 'output_dir', 'drt_data'))
    default_session_prefix = get_config_str(config, 'session_prefix', 'drt')
    default_console = get_config_bool(config, 'console_output', False)
    default_auto_start = get_config_bool(config, 'auto_start_recording', False)

    parser = argparse.ArgumentParser(
        description=f"{MODULE_NAME} - {MODULE_DESCRIPTION}"
    )

    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=["gui", "simple"],
        default_mode="gui",
        default_session_prefix=default_session_prefix,
        default_console_output=default_console,
        default_auto_start_recording=default_auto_start,
    )

    parser.add_argument(
        "--session-dir",
        type=Path,
        default=None,
        help="Session directory (auto-generated if not specified)"
    )

    args = parser.parse_args(argv)

    args.window_geometry = load_window_geometry_from_config(config, args.window_geometry)

    args.enable_gui_commands = args.enable_commands

    args.device_vid = config.get('device_vid', 0x239A)
    args.device_pid = config.get('device_pid', 0x801F)
    args.baudrate = get_config_int(config, 'baudrate', 9600)

    args.config = config
    args.config_file_path = config_path

    return args


async def main():
    args = parse_args()

    args.output_dir = ensure_directory(args.output_dir)

    module_dir = Path(__file__).parent
    session_name, log_file, is_command_mode = setup_module_logging(
        args,
        module_name='drt',
        module_dir=module_dir,
        default_prefix='drt'
    )

    log_module_startup(
        logger,
        session_name,
        log_file,
        args,
        module_name="DRT",
        session_directory=args.session_dir,
        output_directory=args.output_dir,
    )

    supervisor = DRTSupervisor(args)
    loop = asyncio.get_running_loop()

    install_exception_handlers(logger, loop)
    install_signal_handlers(supervisor, loop, track_shutdown_state=True)

    try:
        await supervisor.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        await supervisor.shutdown()
        log_module_shutdown(logger, "DRT")


if __name__ == "__main__":
    asyncio.run(main())
