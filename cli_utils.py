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
    console_output: bool = True,
) -> None:
    """
    Configure root logging with optional file output.

    Args:
        level_name: Logging level (debug, info, warning, error, critical)
        log_file: Optional path to write logs to file
        suppressed_loggers: Logger names to suppress (set to ERROR level)
        fmt: Log message format
        datefmt: Date/time format
        console_output: If True, also log to console. If False, only log to file.
    """

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

    # Add console handler if requested
    if console_output:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    # Add file handler if log_file specified
    if log_file:
        log_file_path = Path(log_file) if not isinstance(log_file, Path) else log_file
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
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


# IMX296 supported resolution presets (sensor native: 1456x1088)
RESOLUTION_PRESETS = {
    # Preset number/name: (width, height, description, aspect_ratio)
    0: (1456, 1088, "Native - Full sensor resolution", "4:3"),
    1: (1280, 960, "SXGA - Slight downscale, minimal crop", "4:3"),
    2: (1280, 720, "HD 720p - Standard HD", "16:9"),
    3: (1024, 768, "XGA - Good balance", "4:3"),
    4: (800, 600, "SVGA - Lower CPU usage", "4:3"),
    5: (640, 480, "VGA - Minimal CPU usage", "4:3"),
    6: (480, 360, "QVGA+ - Very low CPU preview", "4:3"),
    7: (320, 240, "QVGA - Ultra minimal preview", "4:3"),
}

# Create reverse lookup: (width, height) -> preset number
RESOLUTION_TO_PRESET = {(w, h): num for num, (w, h, _, _) in RESOLUTION_PRESETS.items()}


def get_resolution_preset_help() -> str:
    """Generate help text for resolution presets."""
    lines = ["Available resolution presets:"]
    for num, (w, h, desc, aspect) in RESOLUTION_PRESETS.items():
        lines.append(f"  {num}: {w}x{h} - {desc} ({aspect})")
    return "\n".join(lines)


def parse_resolution(value: str) -> Tuple[int, int]:
    """
    Parse resolution from preset number (0-5 only).

    Args:
        value: A preset number (0-5)

    Returns:
        (width, height) tuple

    Raises:
        argparse.ArgumentTypeError: If value is invalid
    """
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

