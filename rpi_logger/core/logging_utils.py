"""Shared logging helpers for the RPi Logger project."""

from __future__ import annotations

import logging
from typing import Optional, Union

MODULE_LOGGER_NAMESPACE = "rpi_logger"
DEFAULT_COMPONENT = "Core"
DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"

_root_configured = False


def _configure_root_logger(level: int = logging.DEBUG) -> None:
    """Ensure the root logger exists and is configured for DEBUG output."""
    global _root_configured
    if _root_configured:
        return
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)
    else:
        root.setLevel(level)
    _root_configured = True


def _normalize_logger_name(name: Optional[str]) -> str:
    if not name:
        return MODULE_LOGGER_NAMESPACE
    if name.startswith(MODULE_LOGGER_NAMESPACE):
        return name
    return f"{MODULE_LOGGER_NAMESPACE}.{name}"


def _derive_component(name: str) -> str:
    if not name:
        return DEFAULT_COMPONENT
    if name.startswith(MODULE_LOGGER_NAMESPACE):
        suffix = name[len(MODULE_LOGGER_NAMESPACE):].lstrip(".")
        return suffix or DEFAULT_COMPONENT
    return name


class StructuredLogger:
    """Lightweight wrapper that enforces consistent DEBUG logging output."""

    __slots__ = ("_logger", "_component")

    def __init__(self, logger: logging.Logger, component: Optional[str] = None) -> None:
        object.__setattr__(self, "_logger", logger)
        resolved_component = component or _derive_component(logger.name)
        object.__setattr__(self, "_component", resolved_component or DEFAULT_COMPONENT)
        # We don't force setLevel(DEBUG) here anymore to respect global config,
        # but we can ensure it's at least NOTSET so it bubbles up.
        # logger.setLevel(logging.DEBUG) 

    # ------------------------------------------------------------------
    # Core plumbing helpers

    def __getattr__(self, item):
        return getattr(self._logger, item)

    def __setattr__(self, key, value):
        if key in self.__slots__:
            object.__setattr__(self, key, value)
        else:
            setattr(self._logger, key, value)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"StructuredLogger({self._logger!r}, component={self._component!r})"

    @property
    def name(self) -> str:
        return self._logger.name

    @property
    def component(self) -> str:
        return self._component

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    # ------------------------------------------------------------------
    # Formatting helpers

    def _compose(self, message: object, args: tuple) -> str:
        text = str(message)
        if args:
            try:
                text = text % args
            except Exception:  # pragma: no cover - defensive
                safe_args = " ".join(str(arg) for arg in args)
                text = f"{text} | args={safe_args}"
        prefix = self._component or DEFAULT_COMPONENT
        if prefix and not text.startswith(f"[{prefix}]"):
            text = f"[{prefix}] {text}"
        return text

    def _emit(self, method: str, message: object, *args, **kwargs) -> None:
        formatted = self._compose(message, args)
        getattr(self._logger, method)(formatted, **kwargs)

    # ------------------------------------------------------------------
    # Logging API surface

    def log(self, level: int, message: object, *args, **kwargs) -> None:
        formatted = self._compose(message, args)
        self._logger.log(level, formatted, **kwargs)

    def debug(self, message: object, *args, **kwargs) -> None:
        self._emit("debug", message, *args, **kwargs)

    def info(self, message: object, *args, **kwargs) -> None:
        self._emit("info", message, *args, **kwargs)

    def warning(self, message: object, *args, **kwargs) -> None:
        self._emit("warning", message, *args, **kwargs)

    warn = warning  # pragma: no cover - legacy alias

    def error(self, message: object, *args, **kwargs) -> None:
        self._emit("error", message, *args, **kwargs)

    def exception(self, message: object, *args, **kwargs) -> None:
        kwargs.setdefault("exc_info", True)
        self._emit("error", message, *args, **kwargs)

    def critical(self, message: object, *args, **kwargs) -> None:
        self._emit("critical", message, *args, **kwargs)

    def getChild(self, suffix: str) -> "StructuredLogger":
        child = self._logger.getChild(suffix)
        child_component = f"{self._component}.{suffix}" if self._component else suffix
        return StructuredLogger(child, component=child_component)


LoggerLike = Union[StructuredLogger, logging.Logger, logging.LoggerAdapter, None]


def ensure_structured_logger(
    logger: LoggerLike,
    *,
    component: Optional[str] = None,
    fallback_name: Optional[str] = None,
) -> StructuredLogger:
    """Return a StructuredLogger wrapping ``logger`` (or a new module logger)."""

    if isinstance(logger, StructuredLogger):
        target = logger
    elif isinstance(logger, logging.LoggerAdapter):
        target = StructuredLogger(logger.logger, component=component or _derive_component(logger.logger.name))
    elif isinstance(logger, logging.Logger):
        target = StructuredLogger(logger, component=component)
    else:
        target = None

    if target is None:
        target = get_module_logger(fallback_name)
    
    return target


def get_module_logger(name: Optional[str] = None) -> StructuredLogger:
    """Return a structured logger scoped to the rpi_logger namespace."""
    # _configure_root_logger() # Defer root config to main entry point
    normalized = _normalize_logger_name(name)
    base = logging.getLogger(normalized)
    return StructuredLogger(base)


__all__ = [
    "StructuredLogger",
    "ensure_structured_logger",
    "get_module_logger",
]
