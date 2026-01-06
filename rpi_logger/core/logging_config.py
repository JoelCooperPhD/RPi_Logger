"""Centralized logging configuration for the Logger project."""

from __future__ import annotations

import contextlib
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable, Optional, Union

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_DEFAULT_MAX_BYTES = 500 * 1024  # 500 KB - keeps logs readable
_DEFAULT_BACKUP_COUNT = 2

_configured = False


def _coerce_level(level: Union[int, str]) -> int:
    if isinstance(level, str):
        name = level.upper()
        if not hasattr(logging, name):
            raise ValueError(f"Unknown log level '{level}'")
        return getattr(logging, name)
    return int(level)


def configure_logging(
    level: Union[int, str] = logging.INFO,
    *,
    force: bool = False,
    console: bool = True,
    log_file: Optional[Union[str, Path]] = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
    suppressed_loggers: Iterable[str] = (),
) -> None:
    """Configure root logging with a consistent formatter and handlers.

    Args:
        level: Desired logging level (int or name such as "info").
        force: When True, always rebuild handlers even if configured.
        console: Whether to emit logs to stdout.
        log_file: Optional path for a rotating file handler.
        max_bytes: Max bytes before rotating the log file.
        backup_count: Number of rotated log files to keep.
        suppressed_loggers: Collection of logger names to silence to ERROR.
    """

    global _configured
    numeric_level = _coerce_level(level)
    root = logging.getLogger()

    if _configured and not force:
        root.setLevel(numeric_level)
        for name in suppressed_loggers:
            logging.getLogger(name).setLevel(logging.ERROR)
        return

    for handler in list(root.handlers):
        root.removeHandler(handler)
        with contextlib.suppress(Exception):
            handler.close()

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATEFMT)

    if console:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(numeric_level)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    if not root.handlers:
        # Fall back to basicConfig so logging at least has one handler.
        logging.basicConfig(level=numeric_level, format=LOG_FORMAT, datefmt=LOG_DATEFMT)

    root.setLevel(numeric_level)

    for name in suppressed_loggers:
        logging.getLogger(name).setLevel(logging.ERROR)

    _configured = True


__all__ = ["configure_logging", "LOG_FORMAT", "LOG_DATEFMT"]
