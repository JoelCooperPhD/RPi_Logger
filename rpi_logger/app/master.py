import argparse
import asyncio
import multiprocessing
import signal
import sys
from pathlib import Path
from typing import Optional

# Force spawn method for subprocesses to avoid libcamera fork issues
# libcamera initializes in parent process during CSI camera discovery,
# and fork() inherits broken state. spawn() starts fresh.
try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    pass  # Already set

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
from rpi_logger.core.paths import CONFIG_PATH, MASTER_LOG_FILE, ensure_directories
from rpi_logger.core.config_manager import get_config_manager
from rpi_logger.core.logging_config import configure_logging
from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.api import APIServer, APIController


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
        description="Logger - Master logging orchestrator for multiple modules"
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

    parser.add_argument(
        "--api",
        action="store_true",
        default=False,
        help="Enable REST API server for programmatic control"
    )

    parser.add_argument(
        "--api-port",
        type=int,
        default=8080,
        help="Port for REST API server (default: 8080)"
    )

    parser.add_argument(
        "--api-host",
        type=str,
        default="127.0.0.1",
        help="Host for REST API server (default: 127.0.0.1)"
    )

    parser.add_argument(
        "--api-debug",
        action="store_true",
        default=False,
        help="Enable API debug mode (verbose errors, request logging)"
    )

    args = parser.parse_args(argv)
    return args


async def _cleanup_logger_system(logger_system: LoggerSystem) -> None:
    """Shared cleanup logic for logger system shutdown."""
    # Shutdown UI observer first to prevent Tcl errors during state changes
    logger_system.shutdown_ui_observer()

    await logger_system.save_running_modules_state()
    await logger_system.cleanup()
    await logger_system.update_running_modules_state_after_cleanup()


async def _setup_api_server(
    args: argparse.Namespace,
    logger_system: LoggerSystem,
    shutdown_coordinator,
) -> Optional[APIServer]:
    """Setup and start the API server if enabled."""
    if not args.api:
        return None

    controller = APIController(logger_system)
    server = APIServer(
        controller=controller,
        host=args.api_host,
        port=args.api_port,
        localhost_only=(args.api_host == "127.0.0.1"),
        debug=args.api_debug,
    )

    await server.start()

    async def cleanup_api():
        await server.stop()

    shutdown_coordinator.register_cleanup(cleanup_api)

    return server


async def run_gui(args, logger_system: LoggerSystem) -> None:
    """Run in GUI mode with Tkinter interface."""
    logger.info("Starting in GUI mode")

    ui = MainWindow(logger_system)
    shutdown_coordinator = get_shutdown_coordinator()
    shutdown_task: Optional[asyncio.Task] = None

    async def cleanup_ui():
        ui._cancel_geometry_save_handle(flush=True)
        ui.cleanup_log_handler()
        await ui.timer_manager.stop_all()
        if ui.root:
            ui.root.destroy()

    shutdown_coordinator.register_cleanup(
        lambda: _cleanup_logger_system(logger_system)
    )
    shutdown_coordinator.register_cleanup(cleanup_ui)

    # Start API server if enabled (cleanup registered inside _setup_api_server)
    await _setup_api_server(args, logger_system, shutdown_coordinator)

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


async def main(argv: Optional[list[str]] = None) -> None:
    """
    Main entry point for the Logger system.

    Runs in GUI mode with Tkinter-based graphical interface.

    Optional REST API (--api flag) can run alongside the GUI,
    providing HTTP endpoints for programmatic control.

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
    logger.info("Logger - Master System Starting")
    logger.info("=" * 60)
    if args.api:
        debug_info = " (debug mode)" if args.api_debug else ""
        logger.info("REST API: http://%s:%d%s", args.api_host, args.api_port, debug_info)
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

    await run_gui(args, logger_system)

    logger.info("=" * 60)
    logger.info("Logger - Master System Stopped")
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
