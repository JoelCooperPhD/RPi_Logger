#!/usr/bin/env python3
"""Compatibility wrapper that forwards to the async gaze tracker."""

import asyncio
import logging

from gaze_async import main as async_main


def run() -> None:
    """Run the async gaze tracker via asyncio.run."""
    logging.getLogger(__name__).warning(
        "Modules/EyeTracker/gaze.py is deprecated; forwarding to gaze_async.py"
    )
    asyncio.run(async_main())


if __name__ == "__main__":
    run()
