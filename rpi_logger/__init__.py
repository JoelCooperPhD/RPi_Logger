"""Top-level package for the reorganized RPi Logger application."""

from __future__ import annotations

import asyncio
from importlib import metadata
from typing import Optional, Sequence

from .app.master import main

try:
    __version__ = metadata.version("rpi-logger")
except metadata.PackageNotFoundError:  # pragma: no cover - local dev
    __version__ = "0.0.0"


def run(argv: Optional[Sequence[str]] = None) -> None:
    """Convenience wrapper that runs the async master entry point."""
    asyncio.run(main(list(argv) if argv is not None else None))


__all__ = ["__version__", "main", "run"]
