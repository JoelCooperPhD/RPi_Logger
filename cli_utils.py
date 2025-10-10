"""Shared helpers for building consistent CLI entry points."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


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
    datefmt: str = "%H:%M:%S",
) -> None:
    """Configure root logging with optional file output."""

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
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
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
) -> None:
    """Inject shared CLI arguments for recorder modules."""

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


def parse_resolution(value: str) -> Tuple[int, int]:
    """Parse WIDTHxHEIGHT formatted strings into integer tuples."""

    try:
        width_str, height_str = value.lower().split("x", 1)
        width = int(width_str)
        height = int(height_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Resolution must be formatted as WIDTHxHEIGHT (e.g. 1280x720)"
        ) from exc

    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Resolution dimensions must be positive integers")

    return width, height


def positive_int(value: str) -> int:
    """Ensure CLI integer parameters are strictly positive."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Value must be an integer") from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def positive_float(value: str) -> float:
    """Ensure CLI floating point parameters are strictly positive."""

    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Value must be a number") from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def ensure_directory(path: Path) -> Path:
    """Create the path if missing and return it for convenience."""

    path.mkdir(parents=True, exist_ok=True)
    return path

