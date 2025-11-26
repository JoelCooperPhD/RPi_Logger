import argparse
import asyncio
import signal
import sys
import time
from pathlib import Path
from typing import Optional

# Add the optional per-project virtualenv (created at repo root) to sys.path so
# scripts launched directly from source can still import installed wheels.
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _PACKAGE_ROOT.parent
_py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
_venv_path = _PROJECT_ROOT / ".venv" / "lib" / _py_version / "site-packages"
if _venv_path.exists() and str(_venv_path) not in sys.path:
    sys.path.insert(0, str(_venv_path))

from rpi_logger.core import LoggerSystem, get_shutdown_coordinator
from rpi_logger.core.ui import MainWindow
from rpi_logger.core.cli import HeadlessController, InteractiveShell
from rpi_logger.core.paths import CONFIG_PATH, MASTER_LOG_FILE, ensure_directories
from rpi_logger.core.config_manager import get_config_manager
from rpi_logger.core.logging_config import configure_logging
from rpi_logger.core.logging_utils import get_module_logger


logger = get_module_logger(__name__)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
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


async def _cleanup_logger_system(logger_system: LoggerSystem, request_geometry: bool) -> None:
    """Shared cleanup logic for logger system shutdown."""
    logger.info("Starting logger system cleanup...")
    state_start = time.time()
    await logger_system.save_running_modules_state()
    logger.info("⏱️  Saved state in %.3fs", time.time() - state_start)

    cleanup_start = time.time()
    await logger_system.cleanup(request_geometry=request_geometry)
    logger.info("⏱️  Logger cleanup in %.3fs", time.time() - cleanup_start)

    update_start = time.time()
    await logger_system.update_running_modules_state_after_cleanup()
    logger.info("⏱️  Finalized restart state in %.3fs", time.time() - update_start)


async def run_gui(args, logger_system: LoggerSystem) -> None:
    """Run in GUI mode with Tkinter interface."""
    logger.info("Starting in GUI mode")

    ui = MainWindow(logger_system)
    shutdown_coordinator = get_shutdown_coordinator()
    shutdown_task: Optional[asyncio.Task] = None

    async def cleanup_ui():
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

    shutdown_coordinator.register_cleanup(
        lambda: _cleanup_logger_system(logger_system, request_geometry=False)
    )
    shutdown_coordinator.register_cleanup(cleanup_ui)

    loop = asyncio.get_running_loop()

    def signal_handler():
        nonlocal shutdown_task
        if shutdown_task is None or shutdown_task.done():
            shutdown_task = asyncio.create_task(
                shutdown_coordinator.initiate_shutdown("signal")
            )

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    try:
        await ui.run()
    except KeyboardInterrupt:
        await shutdown_coordinator.initiate_shutdown("keyboard interrupt")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        await shutdown_coordinator.initiate_shutdown("exception")
    finally:
        if not shutdown_coordinator.is_complete:
            await shutdown_coordinator.initiate_shutdown("finally block")


async def run_cli(args, logger_system: LoggerSystem) -> None:
    """Run in CLI interactive mode."""
    logger.info("Starting in CLI interactive mode")

    controller = HeadlessController(logger_system)
    shell = InteractiveShell(controller)
    shutdown_coordinator = get_shutdown_coordinator()
    shutdown_task: Optional[asyncio.Task] = None

    shutdown_coordinator.register_cleanup(
        lambda: _cleanup_logger_system(logger_system, request_geometry=True)
    )

    loop = asyncio.get_running_loop()

    def signal_handler():
        nonlocal shutdown_task
        if shutdown_task is None or shutdown_task.done():
            shutdown_task = asyncio.create_task(
                shutdown_coordinator.initiate_shutdown("signal")
            )

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    await controller.auto_start_modules()

    try:
        await shell.run()
    except KeyboardInterrupt:
        await shutdown_coordinator.initiate_shutdown("keyboard interrupt")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        await shutdown_coordinator.initiate_shutdown("exception")
    finally:
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

    configure_logging(
        args.log_level,
        force=True,
        console=args.console_output,
        log_file=MASTER_LOG_FILE,
    )

    logger.info("=" * 60)
    logger.info("RPi Logger - Master System Starting")
    logger.info("=" * 60)
    logger.info("Mode: %s", args.mode)
    logger.info("Data directory: %s", args.data_dir)
    logger.info("Log file: %s", MASTER_LOG_FILE)
    logger.info("Session will be created when user starts recording")
    logger.info("=" * 60)

    initial_session_dir = args.data_dir.resolve()

    logger_system = LoggerSystem(
        session_dir=initial_session_dir,
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

def run(argv: Optional[list[str]] = None) -> int:
    try:
        asyncio.run(main(argv))
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as exc:  # pragma: no cover - fatal guard
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
