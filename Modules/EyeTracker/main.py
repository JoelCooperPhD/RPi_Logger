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

from config import Config
from gaze_tracker import GazeTracker

SUPPRESSED_LOGGERS = ["pupil_labs", "aiortsp", "websockets", "aiohttp"]

LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def configure_logging(level_name: str, log_file: Optional[Path]) -> None:
    """Configure root logging with optional file output and suppression."""

    level = LOG_LEVELS.get(level_name.lower())
    if level is None:
        valid = ", ".join(sorted(LOG_LEVELS))
        raise ValueError(f"Invalid log level '{level_name}'. Choose from: {valid}")

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    root.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    for logger_name in SUPPRESSED_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.ERROR)


def parse_resolution(value: str) -> tuple[int, int]:
    """Parse WIDTHxHEIGHT strings with strong validation."""

    try:
        width_str, height_str = value.lower().split("x", 1)
        width = int(width_str)
        height = int(height_str)
    except ValueError as exc:  # pragma: no cover - defensive parsing
        raise argparse.ArgumentTypeError(
            "Resolution must be formatted as WIDTHxHEIGHT (e.g. 1280x720)"
        ) from exc

    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Resolution dimensions must be positive integers")

    return width, height


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
    parser.add_argument("--fps", type=float, default=5.0, help="Target processing FPS")
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default="1280x720",
        help="Scene video resolution as WIDTHxHEIGHT",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("video_out"),
        help="Directory where recordings will be stored",
    )
    parser.add_argument(
        "--display-width",
        type=int,
        default=640,
        help="Width of the preview window (maintains aspect ratio)",
    )
    parser.add_argument(
        "--log-level",
        choices=sorted(LOG_LEVELS.keys()),
        default="info",
        help="Root logging level",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional path to a log file for persistent diagnostics",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Number of additional connection attempts (-1 for infinite)",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=5.0,
        help="Seconds to wait between connection attempts",
    )

    args = parser.parse_args(argv)

    configure_logging(args.log_level, args.log_file)
    logger = logging.getLogger("eye_tracker.main")
    logger.debug("Parsed CLI arguments: %s", args)

    if args.display_width <= 0:
        parser.error("--display-width must be a positive integer")
    if args.fps <= 0:
        parser.error("--fps must be a positive value")
    if args.retry_delay <= 0:
        parser.error("--retry-delay must be a positive value")

    width, height = args.resolution if isinstance(args.resolution, tuple) else parse_resolution(args.resolution)

    config = Config(
        fps=args.fps,
        resolution=(width, height),
        output_dir=str(args.output),
        display_width=args.display_width,
    )

    logger.info(
        "Starting gaze tracker with resolution %dx%d @ %.1f FPS (max retries: %s)",
        width,
        height,
        args.fps,
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
