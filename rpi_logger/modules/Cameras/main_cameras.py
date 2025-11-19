"""Compatibility shim for the moved Cameras entry point."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Optional

MODULE_DIR = Path(__file__).resolve().parent


def _find_project_root(start: Path) -> Path:
    for parent in start.parents:
        if parent.name == "rpi_logger":
            return parent.parent
    return start.parents[-1]


PROJECT_ROOT = _find_project_root(MODULE_DIR)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

if __package__ in {None, ""}:
    __package__ = "rpi_logger.modules.Cameras"

from .app.main_cameras import *  # noqa: F401,F403
from .app.main_cameras import main as _app_main
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)
logger.debug("main_cameras shim imported")


async def main(argv: Optional[list[str]] = None) -> None:
    """Entry point invoked by the module manager discovery logic."""
    logger.debug("Delegating Cameras entry point to app layer")
    await _app_main(argv)

if __name__ == "__main__":
    logger.debug("main_cameras shim executing entrypoint")
    asyncio.run(main())
