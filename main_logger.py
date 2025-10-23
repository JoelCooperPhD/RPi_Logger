
import argparse
import asyncio
import datetime
import logging
from logging.handlers import RotatingFileHandler
import signal
import sys
from pathlib import Path
from typing import Optional

from logger_core import LoggerSystem
from logger_core.ui import MenuUI


logger = logging.getLogger(__name__)


def load_config_file(config_path: Path = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).parent / "config.txt"

    config = {}

    if not config_path.exists():
        return config

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    if '#' in value:
                        value = value.split('#')[0].strip()

                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    config[key] = value
    except Exception as e:
        logger.warning("Failed to load config from %s: %s", config_path, e)

    return config


def parse_args(argv: Optional[list[str]] = None):
    config = load_config_file()

    def get_config_str(key, default):
        return config.get(key, default)

    def get_config_bool(key, default):
        if key in config:
            value = config[key]
            if isinstance(value, bool):
                return value
            return str(value).lower() in ('true', '1', 'yes', 'on')
        return default

    default_data_dir = Path(get_config_str('data_dir', 'data'))
    default_session_prefix = get_config_str('session_prefix', 'session')
    default_log_level = get_config_str('log_level', 'info')
    default_console_output = get_config_bool('console_output', True)

    parser = argparse.ArgumentParser(
        description="RPi Logger - Master logging orchestrator for multiple modules"
    )

    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help="Root directory for all logging data (default: data/)"
    )

    parser.add_argument(
        "--session-prefix",
        type=str,
        default=default_session_prefix,
        help="Prefix for session directories (default: session)"
    )

    parser.add_argument(
        "--log-level",
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        default=default_log_level,
        help="Logging level (default: info)"
    )

    parser.add_argument(
        "--console",
        dest="console_output",
        action="store_true",
        default=default_console_output,
        help="Also log to console"
    )

    parser.add_argument(
        "--no-console",
        dest="console_output",
        action="store_false",
        help="Log to file only"
    )

    args = parser.parse_args(argv)
    return args


def configure_logging(log_level: str, log_file: Path, console_output: bool = True) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=20 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)

    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    args.data_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_name = f"{args.session_prefix}_{timestamp}"
    session_dir = args.data_dir / session_name
    session_dir.mkdir(parents=True, exist_ok=True)

    log_file = session_dir / "master.log"
    configure_logging(args.log_level, log_file, console_output=args.console_output)

    logger.info("=" * 60)
    logger.info("RPi Logger - Master System Starting")
    logger.info("=" * 60)
    logger.info("Session: %s", session_name)
    logger.info("Session directory: %s", session_dir)
    logger.info("Log file: %s", log_file)
    logger.info("=" * 60)

    logger_system = LoggerSystem(
        session_dir=session_dir,
        session_prefix=args.session_prefix,
        log_level=args.log_level,
    )

    modules = logger_system.get_available_modules()
    logger.info("Discovered %d modules:", len(modules))
    for module in modules:
        logger.info("  - %s: %s", module.name, module.entry_point)

    ui = MenuUI(logger_system)

    loop = asyncio.get_running_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(shutdown())

    async def shutdown():
        logger.info("Shutting down...")
        try:
            await logger_system.cleanup()
        except Exception as e:
            logger.error("Error during cleanup: %s", e)
        finally:
            if ui.root:
                ui.root.quit()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await ui.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
    finally:
        await logger_system.cleanup()
        logger.info("=" * 60)
        logger.info("RPi Logger - Master System Stopped")
        logger.info("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
