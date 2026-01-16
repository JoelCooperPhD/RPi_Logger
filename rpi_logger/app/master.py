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


def run_gui(args, logger_system: LoggerSystem, api_server: Optional[APIServer] = None) -> None:
    """Run in GUI mode with Tkinter interface.

    This function runs the Tkinter mainloop on the main thread.
    Async operations run in a background thread via AsyncBridge.
    """
    logger.debug("Starting in GUI mode")

    ui = MainWindow(logger_system)
    shutdown_requested = False

    def cleanup_ui_sync():
        ui._cancel_geometry_save_handle(flush=True)
        ui.cleanup_log_handler()
        if ui.root:
            try:
                ui.root.destroy()
            except Exception:
                pass

    def signal_handler(signum, frame):
        nonlocal shutdown_requested
        if not shutdown_requested:
            shutdown_requested = True
            logger.info("Signal %s received, initiating shutdown", signum)
            # Trigger proper async shutdown via controller (same as X button)
            # This ensures cleanup runs before quit
            if ui.controller:
                ui.controller.on_shutdown()
            elif ui.root:
                # Fallback if controller not available
                try:
                    ui.root.quit()
                except Exception:
                    pass

    # Install signal handlers
    old_sigint = signal.signal(signal.SIGINT, signal_handler)
    old_sigterm = signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Run the UI (blocks until window closes)
        ui.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
    finally:
        # Restore original signal handlers
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)

        # Cleanup UI synchronously
        cleanup_ui_sync()


async def _async_cleanup(logger_system: LoggerSystem, api_server: Optional[APIServer] = None) -> None:
    """Run async cleanup after GUI closes."""
    shutdown_coordinator = get_shutdown_coordinator()

    # Stop API server if running
    if api_server:
        try:
            await api_server.stop()
        except Exception as e:
            logger.error("Error stopping API server: %s", e)

    # Run the standard cleanup
    if not shutdown_coordinator.is_complete:
        await _cleanup_logger_system(logger_system)


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
        logger.debug("REST API: http://%s:%d%s", args.api_host, args.api_port, debug_info)
    logger.debug("Data directory: %s", args.data_dir)
    logger.debug("Log file: %s", MASTER_LOG_FILE)
    logger.debug("Session will be created when user starts recording")
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
    logger.debug("Discovered %d modules:", len(modules))
    for module in modules:
        logger.debug("  - %s: %s", module.name, module.entry_point)

    # Start API server if enabled (async)
    shutdown_coordinator = get_shutdown_coordinator()
    api_server = await _setup_api_server(args, logger_system, shutdown_coordinator)

    # Run GUI (synchronous - blocks until window closes)
    # AsyncBridge handles async operations in background thread
    run_gui(args, logger_system, api_server)

    # Async cleanup after GUI closes
    await _async_cleanup(logger_system, api_server)

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
