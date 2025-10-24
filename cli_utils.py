from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple


LOG_LEVELS: dict[str, int] = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def configure_logging(
    level_name: str,
    log_file: Optional[Path] = None,
    *,
    suppressed_loggers: Iterable[str] = (),
    fmt: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
    console_output: bool = True,
) -> None:
    level = LOG_LEVELS.get(level_name.lower())
    if level is None:
        valid = ", ".join(sorted(LOG_LEVELS))
        raise ValueError(f"Invalid log level '{level_name}'. Choose from: {valid}")

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    root.setLevel(level)

    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    if console_output:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    if log_file:
        log_file_path = Path(log_file) if not isinstance(log_file, Path) else log_file
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=20 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    for name in suppressed_loggers:
        logging.getLogger(name).setLevel(logging.ERROR)


def add_common_cli_arguments(
    parser: argparse.ArgumentParser,
    *,
    default_output: Path | str,
    allowed_modes: Optional[Sequence[str]] = None,
    default_mode: Optional[str] = None,
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

    if allowed_modes:
        choices = list(dict.fromkeys(allowed_modes))
        parser.add_argument(
            "--mode",
            choices=choices,
            default=default_mode or (choices[0] if choices else None),
            help="Execution mode",
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


RESOLUTION_PRESETS = {
    0: (1456, 1088, "Native - Full sensor resolution", "4:3"),
    1: (1280, 960, "SXGA - Slight downscale, minimal crop", "4:3"),
    2: (1280, 720, "HD 720p - Standard HD", "16:9"),
    3: (1024, 768, "XGA - Good balance", "4:3"),
    4: (800, 600, "SVGA - Lower CPU usage", "4:3"),
    5: (640, 480, "VGA - Minimal CPU usage", "4:3"),
    6: (480, 360, "QVGA+ - Very low CPU preview", "4:3"),
    7: (320, 240, "QVGA - Ultra minimal preview", "4:3"),
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


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Value must be an integer") from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Value must be a number") from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_int(config: dict, key: str, default: int) -> int:
    return int(config.get(key, default)) if key in config else default


def get_config_float(config: dict, key: str, default: float) -> float:
    return float(config.get(key, default)) if key in config else default


def get_config_bool(config: dict, key: str, default: bool) -> bool:
    if key in config:
        value = config[key]
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('true', '1', 'yes', 'on')
    return default


def get_config_str(config: dict, key: str, default: str) -> str:
    return config.get(key, default)


def setup_module_logging(
    args: Any,
    module_name: str,
    module_dir: Path,
    default_prefix: str = 'session'
) -> Tuple[str, Path, bool]:
    from Modules.base import setup_session_from_args, redirect_stderr_stdout

    session_dir, session_name, is_command_mode = setup_session_from_args(
        args,
        default_prefix=default_prefix
    )

    logs_dir = module_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / f"{module_name}.log"

    original_stdout = redirect_stderr_stdout(log_file)

    if is_command_mode:
        from logger_core.commands import StatusMessage
        StatusMessage.configure(original_stdout)

    configure_logging(args.log_level, str(log_file), console_output=args.console_output)

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


def install_signal_handlers(
    supervisor: Any,
    loop: asyncio.AbstractEventLoop,
    track_shutdown_state: bool = False
) -> None:
    if track_shutdown_state:
        # Track shutdown state to prevent race conditions (used by Audio module)
        shutdown_in_progress = False

        def signal_handler():
            nonlocal shutdown_in_progress
            if not supervisor.shutdown_event.is_set() and not shutdown_in_progress:
                shutdown_in_progress = True
                asyncio.create_task(supervisor.shutdown())
    else:
        def signal_handler():
            if not supervisor.shutdown_event.is_set():
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
    logger.info("Mode: %s", args.mode)

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

