"""Compatibility shim for the moved Cameras entry point."""

from __future__ import annotations

import asyncio

from .app.main_cameras import *  # noqa: F401,F403
from .app.main_cameras import main as _app_main

if __name__ == "__main__":
    asyncio.run(_app_main())
