#!/usr/bin/env python3
"""Interactive helper for running audio/video muxing over a session directory."""

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from rpi_logger.core.logging_config import configure_logging
from rpi_logger.core.logging_utils import get_module_logger

from .sync_and_mux import discover_trial_numbers, process_session

configure_logging()
logger = get_module_logger("muxing_tool")


def _prompt_for_session_dir(allow_gui: bool) -> Optional[Path]:
    """Prompt the user for a session directory, optionally via Tk dialog."""
    if allow_gui:
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            selected = filedialog.askdirectory(title="Select session folder for muxing")
            root.destroy()
            if selected:
                return Path(selected)
        except Exception as exc:  # pragma: no cover - tkinter may be unavailable
            logger.warning("GUI folder picker unavailable (%s); falling back to console prompt.", exc)

    try:
        user_input = input("Enter session directory path: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    return Path(user_input) if user_input else None


async def _run_mux(session_dir: Path) -> int:
    trial_numbers = discover_trial_numbers(session_dir)
    if not trial_numbers:
        logger.warning("No trial files found in %s", session_dir)
        return 1

    await process_session(session_dir, trial_numbers, mux=True)
    logger.info("Finished muxing %d trial(s) in %s", len(trial_numbers), session_dir)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select a session directory and mux every trial inside it"
    )
    parser.add_argument(
        "--session",
        type=Path,
        help="Path to the session directory (skips interactive prompt)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Disable the Tk folder picker even if a display is available",
    )

    args = parser.parse_args()

    session_path = args.session
    if session_path is None:
        session_path = _prompt_for_session_dir(allow_gui=not args.no_gui)
        if session_path is None:
            logger.warning("Session directory selection was cancelled")
            return 1

    session_path = session_path.expanduser().resolve()

    if not session_path.exists():
        logger.error("Selected path does not exist: %s", session_path)
        return 1

    if not session_path.is_dir():
        logger.error("Selected path is not a directory: %s", session_path)
        return 1

    logger.info("Starting mux run for %s", session_path)
    return asyncio.run(_run_mux(session_path))


if __name__ == "__main__":
    raise SystemExit(main())
