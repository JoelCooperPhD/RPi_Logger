"""VOG (Visual Occlusion Glasses) module entry point.

This module controls sVOG devices for visual occlusion experiments.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

MODULE_DIR = Path(__file__).resolve().parent


async def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for VOG module.

    TODO: Implement in Task 8.
    """
    pass


if __name__ == "__main__":
    asyncio.run(main())
