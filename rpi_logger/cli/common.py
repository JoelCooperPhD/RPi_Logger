from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from pathlib import Path
from typing import Any, Optional, Tuple

from rpi_logger.core.logging_config import configure_logging
from rpi_logger.core.paths import USER_MODULE_LOGS_DIR
from rpi_logger.core.logging_utils import get_module_logger


LOG_LEVELS: dict[str, int] = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def add_common_cli_arguments(
    parser: argparse.ArgumentParser,
    *,
    default_output: Path | str,
    include_config: bool = False,
    include_session_prefix: bool = True,
    default_session_prefix: str = "session",
    include_console_control: bool = True,
    default_console_output: bool = False,
    include_auto_recording: bool = True,
    default_auto_start_recording: bool = False,
    include_parent_control: bool = True,
    include_window_geometry: bool = True,
) -> None:
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(default_output),
        help="Directory where recordings or artifacts will be stored",
    )

    parser.add_argument(
        "--log-level",
        choices=sorted(LOG_LEVELS.keys()),
        default="info",
        help="Logging verbosity",
    )

    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional path to write structured logs",
    )

    if include_config:
        parser.add_argument(
            "--config",
            type=Path,
            default=None,
            help="Optional configuration file that overrides CLI arguments",
        )

    if include_session_prefix:
        parser.add_argument(
            "--session-prefix",
            type=str,
            default=default_session_prefix,
            help="Prefix for generated session directories",
        )

    if include_console_control:
        console_group = parser.add_mutually_exclusive_group()
        console_group.add_argument(
            "--console",
            dest="console_output",
            action="store_true",
            default=default_console_output,
            help="Also log to console (in addition to file)",
        )
        console_group.add_argument(
            "--no-console",
            dest="console_output",
            action="store_false",
            help="Log to file only (no console output)",
        )

    if include_auto_recording:
        recording_group = parser.add_mutually_exclusive_group()
        recording_group.add_argument(
            "--auto-start-recording",
            dest="auto_start_recording",
            action="store_true",
            default=default_auto_start_recording,
            help="Automatically start recording on startup",
        )
        recording_group.add_argument(
            "--no-auto-start-recording",
            dest="auto_start_recording",
            action="store_false",
            help="Wait for manual recording command (default)",
        )

    if include_parent_control:
        parser.add_argument(
            "--enable-commands",
            dest="enable_commands",
            action="store_true",
            default=False,
            help="Enable JSON command interface for parent process control (auto-detected if stdin is piped)",
        )

    if include_window_geometry:
        parser.add_argument(
            "--window-geometry",
            dest="window_geometry",
            type=str,
            default=None,
            help="Window position and size (format: WIDTHxHEIGHT+X+Y, e.g., 800x600+100+50)",
        )

    # Instance ID for multi-instance modules (e.g., DRT:ACM0, DRT:ACM1)
    parser.add_argument(
        "--instance-id",
        dest="instance_id",
        type=str,
        default=None,
        help="Instance ID for multi-instance modules (e.g., DRT:ACM0). Used for per-instance geometry persistence.",
    )

    # Instance-specific config path for multi-instance modules
    parser.add_argument(
        "--config-path",
        dest="config_path",
        type=Path,
        default=None,
        help="Instance-specific config file path (set by parent process for multi-instance modules).",
    )

    # Platform information (passed from parent process)
    parser.add_argument(
        "--platform",
        dest="platform",
        type=str,
        default=None,
        help="Platform identifier (linux, darwin, win32). Set by parent process.",
    )
    parser.add_argument(
        "--architecture",
        dest="architecture",
        type=str,
        default=None,
        help="CPU architecture (x86_64, arm64, aarch64, armv7l). Set by parent process.",
    )
    parser.add_argument(
        "--is-raspberry-pi",
        dest="is_raspberry_pi",
        action="store_true",
        default=False,
        help="Running on Raspberry Pi hardware. Set by parent process.",
    )


RESOLUTION_PRESETS = {
    0: (1456, 1088, "Native - Full sensor resolution", "4:3"),
    1: (1280, 960, "SXGA - Slight downscale, minimal crop", "4:3"),
    2: (1280, 720, "HD 720p - Standard HD", "16:9"),
    3: (1024, 768, "XGA - Good balance", "4:3"),
    4: (800, 600, "SVGA - Lower CPU usage", "4:3"),
    5: (640, 480, "VGA - Minimal CPU usage", "4:3"),
    6: (480, 360, "QVGA+ - Very low CPU preview", "4:3"),
    7: (320, 240, "QVGA - Ultra minimal preview", "4:3"),
    8: (240, 180, "Tiny - Extra small preview", "4:3"),
    9: (160, 120, "Micro - Minimal window size", "4:3"),
}

RESOLUTION_TO_PRESET = {(w, h): num for num, (w, h, _, _) in RESOLUTION_PRESETS.items()}


def get_resolution_preset_help() -> str:
    lines = ["Available resolution presets:"]
    for num, (w, h, desc, aspect) in RESOLUTION_PRESETS.items():
        lines.append(f"  {num}: {w}x{h} - {desc} ({aspect})")
    return "\n".join(lines)


def parse_resolution(value: str) -> Tuple[int, int]:
    try:
        preset_num = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Resolution must be a preset number (0-{len(RESOLUTION_PRESETS)-1}).\n"
            f"{get_resolution_preset_help()}"
        ) from exc

    if preset_num in RESOLUTION_PRESETS:
        width, height, _, _ = RESOLUTION_PRESETS[preset_num]
        return width, height
    else:
        valid_presets = ", ".join(str(k) for k in sorted(RESOLUTION_PRESETS.keys()))
        raise argparse.ArgumentTypeError(
            f"Invalid resolution preset '{preset_num}'. "
            f"Valid presets: {valid_presets}\n{get_resolution_preset_help()}"
        )


def _positive_number(value: str, typ: type, name: str):
    """Generic positive number validator for argparse."""
    try:
        parsed = typ(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Value must be a {name}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed

def positive_int(value: str) -> int:
    return _positive_number(value, int, "integer")

def positive_float(value: str) -> float:
    return _positive_number(value, float, "number")


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_config_value(config: dict, key: str, default, converter=None):
    """Generic config value getter with optional type conversion."""
    if key not in config:
        return default
    value = config[key]
    if converter:
        try:
            return converter(value)
        except Exception:
            return default
    return value

def get_config_int(config: dict, key: str, default: int) -> int:
    return _get_config_value(config, key, default, int)

def get_config_float(config: dict, key: str, default: float) -> float:
    return _get_config_value(config, key, default, float)

def get_config_bool(config: dict, key: str, default: bool) -> bool:
    if key not in config:
        return default
    value = config[key]
    if isinstance(value, bool):
        return value
    return str(value).lower() in ('true', '1', 'yes', 'on')

def get_config_str(config: dict, key: str, default: str) -> str:
    return config.get(key, default)

def get_config_path(config: dict, key: str, default: Path) -> Path:
    """Get a Path value from config, returning default if missing or invalid."""
    if key not in config or config[key] is None:
        return default
    text = str(config[key]).strip()
    return Path(text) if text else default


def add_config_to_args(
    parser: argparse.ArgumentParser,
    config_context: "ModuleConfigContext",
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Load config file and return values for CLI argument defaulting.

    This is the unified entry point for modules to load their config files
    during argument parsing. It:
    1. Loads the config file from the writable path
    2. Merges with provided defaults
    3. Sets the config_path as a parser default

    Args:
        parser: ArgumentParser to configure with config_path default.
        config_context: Module config context from resolve_module_config_path().
        defaults: Default values dict (keys should match config file keys).

    Returns:
        Loaded config dict with defaults applied, for use in setting CLI defaults.

    Example:
        config_ctx = resolve_module_config_path(MODULE_DIR, MODULE_ID)
        defaults = asdict(MyModuleConfig())
        config = add_config_to_args(parser, config_ctx, defaults)

        add_common_cli_arguments(
            parser,
            default_output=config.get("output_dir", defaults["output_dir"]),
            ...
        )
    """
    from rpi_logger.modules.base.config_loader import ConfigLoader

    config = ConfigLoader.load(config_context.writable_path, defaults, strict=False)

    # Store config path in parser defaults for later access
    parser.set_defaults(config_path=config_context.writable_path)

    return config


# Type import for type checking only
if False:  # TYPE_CHECKING equivalent that works at runtime
    from rpi_logger.modules.base.config_paths import ModuleConfigContext


def _try_prepare_log_destination(directory: Path, filename: str) -> tuple[Path | None, Exception | None]:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        log_file = directory / filename
        log_file.touch(exist_ok=True)
        return log_file, None
    except Exception as exc:  # pragma: no cover - fallback path handles errors
        return None, exc


def _prepare_log_file(module_dir: Path, module_name: str) -> tuple[Path, bool, str | None]:
    """Select a writable log destination, falling back to the user state dir."""

    from rpi_logger.modules.base import sanitize_path_component

    preferred_dir = module_dir / "logs"
    filename = f"{module_name}.log"
    preferred_log, preferred_error = _try_prepare_log_destination(preferred_dir, filename)
    if preferred_log:
        return preferred_log, False, None

    fallback_dir = USER_MODULE_LOGS_DIR / sanitize_path_component(module_name or "module")
    fallback_log, fallback_error = _try_prepare_log_destination(fallback_dir, filename)
    if fallback_log:
        reason = f"{preferred_dir}: {preferred_error}" if preferred_error else str(preferred_dir)
        return fallback_log, True, reason

    raise PermissionError(
        "Unable to create module log file in %s (error: %s) or fallback %s (error: %s)"
        % (preferred_dir, preferred_error, fallback_dir, fallback_error)
    )


def setup_module_logging(
    args: Any,
    module_name: str,
    module_dir: Path,
    default_prefix: str = 'session'
) -> Tuple[str, Path, bool]:
    from rpi_logger.modules.base import setup_session_from_args, redirect_stderr_stdout

    session_dir, session_name, is_command_mode = setup_session_from_args(
        args,
        default_prefix=default_prefix
    )

    log_file, used_fallback, fallback_reason = _prepare_log_file(module_dir, module_name)

    original_stdout = redirect_stderr_stdout(log_file)

    if is_command_mode:
        from rpi_logger.core.commands import StatusMessage
        StatusMessage.configure(original_stdout)

    configure_logging(
        args.log_level,
        force=True,
        console=args.console_output,
        log_file=log_file,
    )

    runtime_logger = get_module_logger(module_name or __name__)
    if used_fallback:
        runtime_logger.warning(
            "Module log directory not writable (%s). Using fallback path %s",
            fallback_reason,
            log_file.parent,
        )
    runtime_logger.info("Module logs will be written to %s", log_file)

    args.session_dir = session_dir
    args.log_file = log_file
    args.console_stdout = original_stdout
    args.command_stdout = original_stdout

    return session_name, log_file, is_command_mode


def install_exception_handlers(
    logger: logging.Logger,
    loop: Optional[asyncio.AbstractEventLoop] = None
) -> None:
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_exception

    if loop is not None:
        def handle_asyncio_exception(loop, context):
            exception = context.get('exception')
            message = context.get('message', 'Unhandled asyncio exception')
            if exception:
                logger.exception(f"Asyncio exception: {message}", exc_info=exception)
            else:
                logger.error(f"Asyncio error: {message}, context: {context}")

        loop.set_exception_handler(handle_asyncio_exception)


def install_signal_handlers(supervisor: Any, loop: asyncio.AbstractEventLoop, track_shutdown_state: bool = False) -> None:
    """Register SIGINT/SIGTERM handlers that ask the supervisor to shut down."""

    shutdown_event = getattr(supervisor, "shutdown_event", None)
    if shutdown_event is None and hasattr(supervisor, "model"):
        shutdown_event = getattr(supervisor.model, "shutdown_event", None)

    if track_shutdown_state:
        shutdown_in_progress = False

        def signal_handler():
            nonlocal shutdown_in_progress
            if shutdown_event is None:
                asyncio.create_task(supervisor.shutdown())
                return
            if not shutdown_event.is_set() and not shutdown_in_progress:
                shutdown_in_progress = True
                asyncio.create_task(supervisor.shutdown())
    else:
        def signal_handler():
            if shutdown_event is None:
                asyncio.create_task(supervisor.shutdown())
                return
            if not shutdown_event.is_set():
                asyncio.create_task(supervisor.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, signal_handler)


def log_module_startup(
    logger: logging.Logger,
    session_name: str,
    log_file: Path,
    args: Any,
    module_name: str = "MODULE",
    **extra_info
) -> None:
    logger.info("=" * 80)
    logger.info(f"========== {module_name.upper()} SYSTEM SESSION START ==========")
    logger.info("=" * 80)
    logger.info("Session: %s", session_name)
    logger.info("Log file: %s", log_file)

    for key, value in extra_info.items():
        display_key = key.replace('_', ' ').title()
        logger.info("%s: %s", display_key, value)

    if hasattr(args, 'console_output'):
        logger.info("Console output: %s", args.console_output)

    logger.info("=" * 80)


def log_module_shutdown(
    logger: logging.Logger,
    module_name: str = "MODULE"
) -> None:
    logger.info("=" * 60)
    logger.info(f"{module_name.title()} System Stopped")
    logger.info("=" * 60)
