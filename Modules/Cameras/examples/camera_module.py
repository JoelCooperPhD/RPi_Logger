#!/usr/bin/env python3
"""Compatibility shim that delegates to the new async main_camera entrypoint."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import main_camera
sys.path.insert(0, str(Path(__file__).parent.parent))

from main_camera import main as async_main


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
