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
    setup_module_logging,
    install_exception_handlers,
    install_signal_handlers,
    log_module_startup,
    log_module_shutdown,
)
from rpi_logger.modules.base import load_window_geometry_from_config
from gps_core import MODULE_NAME, MODULE_DESCRIPTION, GPSSupervisor, load_config_file
from gps_core.constants import SERIAL_PORT, BAUD_RATE

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    config_path = Path(__file__).parent / "config.txt"
    config = load_config_file(config_path)

    default_output = Path(get_config_str(config, 'output_dir', 'data'))
    default_session_prefix = get_config_str(config, 'session_prefix', 'session')
    default_console = get_config_bool(config, 'console_output', True)

    default_serial_port = get_config_str(config, 'serial_port', SERIAL_PORT)
    baud_rate_raw = get_config_str(config, 'baud_rate', str(BAUD_RATE))
    try:
        default_baud_rate = int(baud_rate_raw)
    except ValueError:
        logger.warning("Invalid baud_rate value '%s' in config – using %d", baud_rate_raw, BAUD_RATE)
        default_baud_rate = BAUD_RATE

    parser = argparse.ArgumentParser(
        description=f"{MODULE_NAME} - {MODULE_DESCRIPTION}"
    )

    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=["gui"],
        default_mode="gui",
        default_session_prefix=default_session_prefix,
        default_console_output=default_console,
        default_auto_start_recording=False,
    )

    parser.add_argument(
        "--serial-port",
        dest="serial_port",
        type=str,
        default=default_serial_port,
        help=f"Serial device path for the GPS receiver (default: {default_serial_port})",
    )

    parser.add_argument(
        "--baud-rate",
        dest="baud_rate",
        type=int,
        default=default_baud_rate,
        help=f"Baud rate for the GPS receiver (default: {default_baud_rate})",
    )

    args = parser.parse_args(argv)

    logger.debug("Command-line window_geometry: %s", args.window_geometry)
    args.window_geometry = load_window_geometry_from_config(config, args.window_geometry)
    logger.debug("Final window_geometry after config load: %s", args.window_geometry)

    args.enable_gui_commands = args.enable_commands
    args.config = config
    args.config_file_path = config_path

    return args


async def main():
    args = parse_args()
    args.output_dir = ensure_directory(args.output_dir)

    module_dir = Path(__file__).parent
    session_name, log_file, is_command_mode = setup_module_logging(
        args,
        module_name='gps',
        module_dir=module_dir,
        default_prefix='session'
    )

    log_module_startup(
        logger,
        session_name,
        log_file,
        args,
        module_name=MODULE_NAME,
    )

    supervisor = GPSSupervisor(args)
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
        log_module_shutdown(logger, MODULE_NAME)


if __name__ == "__main__":
    asyncio.run(main())
