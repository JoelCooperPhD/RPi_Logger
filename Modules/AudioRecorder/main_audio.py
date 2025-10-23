
import argparse
import asyncio
import contextlib
import logging
import os
import re
import signal
import sys
from pathlib import Path
from typing import Optional

try:
    from cli_utils import (
        add_common_cli_arguments,
        ensure_directory,
        positive_int,
        get_config_int,
        get_config_float,
        get_config_bool,
        get_config_str,
        setup_module_logging,
        install_exception_handlers,
        install_signal_handlers,
        log_module_startup,
        log_module_shutdown,
    )
except ImportError as e:
    print(f"ERROR: Cannot import required modules. Ensure PYTHONPATH includes project root or install package.", file=sys.stderr)
    print(f"  Add to PYTHONPATH: export PYTHONPATH=/home/rs-pi-2/Development/RPi_Logger:$PYTHONPATH", file=sys.stderr)
    print(f"  Or install package: cd /home/rs-pi-2/Development/RPi_Logger && pip install -e .", file=sys.stderr)
    sys.exit(1)

# Note: audio_core import is delayed until after stderr/stdout redirection

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    # Load config file first (import here to avoid loading audio libraries early)
    from audio_core import load_config_file
    config = load_config_file()

    default_sample_rate = get_config_int(config, 'sample_rate', 48000)
    default_output = Path(get_config_str(config, 'output_dir', 'recordings'))
    default_session_prefix = get_config_str(config, 'session_prefix', 'experiment')
    default_auto_select_new = get_config_bool(config, 'auto_select_new', True)
    default_auto_start_recording = get_config_bool(config, 'auto_start_recording', False)
    default_console_output = get_config_bool(config, 'console_output', False)
    default_discovery_timeout = get_config_float(config, 'discovery_timeout', 5.0)
    default_discovery_retry = get_config_float(config, 'discovery_retry', 3.0)

    parser = argparse.ArgumentParser(description="Multi-microphone audio recorder")
    add_common_cli_arguments(
        parser,
        default_output=default_output,
        allowed_modes=("gui", "headless"),
        default_mode="gui",
        default_session_prefix=default_session_prefix,
        default_console_output=default_console_output,
        default_auto_start_recording=default_auto_start_recording,
    )

    parser.add_argument(
        "--sample-rate",
        type=positive_int,
        default=default_sample_rate,
        help="Sample rate (Hz) for each active microphone",
    )

    auto_select_group = parser.add_mutually_exclusive_group()
    auto_select_group.add_argument(
        "--auto-select-new",
        dest="auto_select_new",
        action="store_true",
        default=default_auto_select_new,
        help="Automatically select newly detected input devices",
    )
    auto_select_group.add_argument(
        "--no-auto-select-new",
        dest="auto_select_new",
        action="store_false",
        help="Disable automatic selection of new devices",
    )

    parser.add_argument(
        "--discovery-timeout",
        type=positive_int,
        default=default_discovery_timeout,
        help="Device discovery timeout (seconds)",
    )
    parser.add_argument(
        "--discovery-retry",
        type=positive_int,
        default=default_discovery_retry,
        help="Device discovery retry interval (seconds)",
    )

    parser.add_argument("--slave", dest="mode", action="store_const", const="slave", help=argparse.SUPPRESS)
    parser.add_argument("--headless", dest="mode", action="store_const", const="headless", help=argparse.SUPPRESS)
    parser.add_argument("--interactive", dest="mode", action="store_const", const="gui", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    from Modules.base import load_window_geometry_from_config
    args.window_geometry = load_window_geometry_from_config(config, args.window_geometry)

    return args


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    args.output_dir = ensure_directory(args.output_dir)

    session_name, log_file, is_command_mode = setup_module_logging(
        args,
        module_name='audio',
        default_prefix='experiment'
    )

    log_module_startup(
        logger,
        session_name,
        log_file,
        args,
        module_name="Audio",
        sample_rate=f"{args.sample_rate} Hz",
    )

    # Import AudioSupervisor AFTER stderr/stdout redirection
    from audio_core import AudioSupervisor

    supervisor = AudioSupervisor(args)
    loop = asyncio.get_running_loop()

    install_exception_handlers(logger, loop)
    install_signal_handlers(supervisor, loop, track_shutdown_state=True)

    try:
        await supervisor.run()
    except Exception as e:
        logger.exception("Unhandled exception in main: %s", e)
        raise  # Re-raise to preserve exit code
    finally:
        if not supervisor.shutdown_event.is_set():
            await supervisor.shutdown()
        log_module_shutdown(logger, "Audio")


if __name__ == "__main__":
    asyncio.run(main())
