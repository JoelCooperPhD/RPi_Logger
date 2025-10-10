#!/usr/bin/env python3
"""Async launcher for the refactored gaze tracker module.

This entry point focuses on discoverability, robust diagnostics, and retries. It
configures logging, validates CLI arguments, and will loop until a connection is
established (respecting the configured retry policy) before handing control to
``GazeTracker``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from cli_utils import (
    add_common_cli_arguments,
    configure_logging,
    parse_resolution,
    positive_float,
    positive_int,
)
from config import Config
from gaze_tracker import GazeTracker

SUPPRESSED_LOGGERS = ["pupil_labs", "aiortsp", "websockets", "aiohttp"]


async def run_with_retries(config: Config, max_retries: int, retry_delay: float) -> int:
    """Attempt to connect/run the tracker with retry + diagnostics."""

    logger = logging.getLogger("eye_tracker.launcher")
    infinite_retries = max_retries < 0
    attempt = 0

    while True:
        attempt += 1
        tracker = GazeTracker(config)
        start = time.perf_counter()
        run_completed = False

        logger.info("Starting connection attempt %d", attempt)
        logger.debug("Tracker configuration: %s", config)

        try:
            try:
                connected = await tracker.connect()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Connection attempt %d raised an error", attempt)
                connected = False

            if connected:
                elapsed = time.perf_counter() - start
                logger.info("Device connected successfully in %.2fs", elapsed)

                await tracker.run()
                run_completed = True
                logger.info("Gaze tracker run finished cleanly")
                return 0

            logger.warning("Connection attempt %d failed to find a device", attempt)

        finally:
            if not run_completed:
                await tracker.cleanup()

        if not infinite_retries and attempt >= max_retries + 1:
            logger.error(
                "Exhausted %d connection attempt(s) without success",
                max_retries + 1,
            )
            return 1

        logger.info("Retrying in %.1fs (attempt %d)", retry_delay, attempt + 1)
        await asyncio.sleep(retry_delay)


async def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point that orchestrates logging, parsing, and retries."""

    parser = argparse.ArgumentParser(description="Refactored Async Gaze Tracker")
    add_common_cli_arguments(
        parser,
        default_output=Path("eye_tracking_data"),
        allowed_modes=("headless",),
        default_mode="headless",
    )
    parser.add_argument(
        "--target-fps",
        dest="target_fps",
        type=positive_float,
        default=5.0,
        help="Target processing FPS",
    )
    parser.add_argument(
        "--fps",
        dest="target_fps",
        type=positive_float,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=(1280, 720),
        help="Scene video resolution as WIDTHxHEIGHT",
    )
    parser.add_argument(
        "--output",
        dest="output_dir",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--preview-width",
        type=positive_int,
        default=640,
        help="Width of the preview window (maintains aspect ratio)",
    )
    parser.add_argument(
        "--display-width",
        dest="preview_width",
        type=positive_int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Number of additional connection attempts (-1 for infinite)",
    )
    parser.add_argument(
        "--retry-delay",
        type=positive_float,
        default=5.0,
        help="Seconds to wait between connection attempts",
    )

    args = parser.parse_args(argv)

    configure_logging(args.log_level, args.log_file, suppressed_loggers=SUPPRESSED_LOGGERS)
    logger = logging.getLogger("eye_tracker.main")
    logger.debug("Parsed CLI arguments: %s", args)

    width, height = args.resolution
    args.output_dir.mkdir(parents=True, exist_ok=True)

    config = Config(
        fps=args.target_fps,
        resolution=(width, height),
        output_dir=str(args.output_dir),
        display_width=args.preview_width,
    )

    logger.info(
        "Starting gaze tracker with resolution %dx%d @ %.1f FPS (max retries: %s)",
        width,
        height,
        args.target_fps,
        "infinite" if args.max_retries < 0 else args.max_retries,
    )

    exit_code = await run_with_retries(config, args.max_retries, args.retry_delay)
    logger.debug("Exiting with code %s", exit_code)
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
