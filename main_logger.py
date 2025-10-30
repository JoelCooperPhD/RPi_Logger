
import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import signal
import sys
from pathlib import Path
from typing import Optional

from logger_core import LoggerSystem, get_shutdown_coordinator
from logger_core.ui import MainWindow
from logger_core.cli import HeadlessController, InteractiveShell
from logger_core.paths import CONFIG_PATH, LOGS_DIR, MASTER_LOG_FILE, ensure_directories
from logger_core.config_manager import get_config_manager


logger = logging.getLogger(__name__)


def parse_args(argv: Optional[list[str]] = None):
    """Parse command-line arguments with config file defaults."""
    config_manager = get_config_manager()
    config = config_manager.read_config(CONFIG_PATH)

    default_data_dir = Path(config_manager.get_str(config, 'data_dir', default='data'))
    default_session_prefix = config_manager.get_str(config, 'session_prefix', default='session')
    default_log_level = config_manager.get_str(config, 'log_level', default='info')
    default_console_output = config_manager.get_bool(config, 'console_output', default=True)

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
        "--mode",
        choices=['gui', 'interactive', 'cli'],
        default='gui',
        help="Execution mode: gui (default, Tkinter UI), interactive (command-line shell), cli (alias for interactive)"
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


async def run_gui(args, logger_system: LoggerSystem) -> None:
    """Run in GUI mode with Tkinter interface."""
    logger.info("Starting in GUI mode")

    ui = MainWindow(logger_system)

    # Setup shutdown coordinator
    shutdown_coordinator = get_shutdown_coordinator()

    # Register cleanup callbacks in order
    async def cleanup_logger_system():
        import time
        logger.info("Starting logger system cleanup...")
        state_start = time.time()
        await logger_system.save_running_modules_state()
        logger.info("⏱️  Saved state in %.3fs", time.time() - state_start)

        cleanup_start = time.time()
        await logger_system.cleanup(request_geometry=False)
        logger.info("⏱️  Logger cleanup in %.3fs", time.time() - cleanup_start)

    async def cleanup_ui():
        import time
        logger.info("Starting UI cleanup...")

        geom_start = time.time()
        ui.save_window_geometry()
        logger.info("⏱️  Saved window geometry in %.3fs", time.time() - geom_start)

        log_start = time.time()
        ui.cleanup_log_handler()
        logger.info("⏱️  Cleaned up log handler in %.3fs", time.time() - log_start)

        timer_start = time.time()
        await ui.timer_manager.stop_all()
        logger.info("⏱️  Stopped timers in %.3fs", time.time() - timer_start)

        if ui.root:
            destroy_start = time.time()
            ui.root.destroy()
            logger.info("⏱️  Destroyed window in %.3fs", time.time() - destroy_start)

    shutdown_coordinator.register_cleanup(cleanup_logger_system)
    shutdown_coordinator.register_cleanup(cleanup_ui)

    # Setup signal handlers
    loop = asyncio.get_running_loop()

    def signal_handler():
        asyncio.create_task(shutdown_coordinator.initiate_shutdown("signal"))

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await ui.run()
    except KeyboardInterrupt:
        await shutdown_coordinator.initiate_shutdown("keyboard interrupt")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        await shutdown_coordinator.initiate_shutdown("exception")
    finally:
        # Ensure shutdown completes if not already initiated
        if not shutdown_coordinator.is_complete:
            await shutdown_coordinator.initiate_shutdown("finally block")


async def run_cli(args, logger_system: LoggerSystem) -> None:
    """Run in CLI interactive mode."""
    logger.info("Starting in CLI interactive mode")

    controller = HeadlessController(logger_system)
    shell = InteractiveShell(controller)

    # Setup shutdown coordinator
    shutdown_coordinator = get_shutdown_coordinator()

    # Register cleanup callback
    async def cleanup_logger_system():
        import time
        logger.info("Starting logger system cleanup...")
        state_start = time.time()
        await logger_system.save_running_modules_state()
        logger.info("⏱️  Saved state in %.3fs", time.time() - state_start)

        cleanup_start = time.time()
        await logger_system.cleanup(request_geometry=True)
        logger.info("⏱️  Logger cleanup in %.3fs", time.time() - cleanup_start)

    shutdown_coordinator.register_cleanup(cleanup_logger_system)

    # Setup signal handlers
    loop = asyncio.get_running_loop()

    def signal_handler():
        asyncio.create_task(shutdown_coordinator.initiate_shutdown("signal"))

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass

    # Auto-start configured modules
    await controller.auto_start_modules()

    try:
        await shell.run()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
    finally:
        # Ensure shutdown completes if not already initiated
        if not shutdown_coordinator.is_complete:
            await shutdown_coordinator.initiate_shutdown("finally block")


async def main(argv: Optional[list[str]] = None) -> None:
    """
    Main entry point for the RPi Logger system.

    Supports two modes:
    - GUI: Tkinter-based graphical interface (default)
    - CLI/Interactive: Command-line shell for remote control

    Shutdown Sequence:
    1. User triggers shutdown via signal (Ctrl+C), UI action, or exception
    2. ShutdownCoordinator.initiate_shutdown() is called with source identifier
    3. Coordinator executes registered cleanup callbacks in order
    4. Finally block ensures shutdown completes
    5. Logs shutdown message and exits

    The ShutdownCoordinator ensures shutdown happens exactly once, regardless
    of how many times it's triggered, preventing race conditions.
    """
    args = parse_args(argv)

    ensure_directories()

    configure_logging(args.log_level, MASTER_LOG_FILE, console_output=args.console_output)

    logger.info("=" * 60)
    logger.info("RPi Logger - Master System Starting")
    logger.info("=" * 60)
    logger.info("Mode: %s", args.mode)
    logger.info("Data directory: %s", args.data_dir)
    logger.info("Log file: %s", MASTER_LOG_FILE)
    logger.info("Session will be created when user starts recording")
    logger.info("=" * 60)

    logger_system = LoggerSystem(
        session_dir=args.data_dir,
        session_prefix=args.session_prefix,
        log_level=args.log_level,
    )

    # Complete async initialization
    await logger_system.async_init()

    modules = logger_system.get_available_modules()
    logger.info("Discovered %d modules:", len(modules))
    for module in modules:
        logger.info("  - %s: %s", module.name, module.entry_point)

    # Route to appropriate mode
    mode = args.mode
    if mode in ('cli', 'interactive'):
        await run_cli(args, logger_system)
    else:
        await run_gui(args, logger_system)

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
