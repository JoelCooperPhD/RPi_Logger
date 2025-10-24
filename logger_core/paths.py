"""
Centralized path constants for the RPi Logger system.

This module provides OS-agnostic path definitions for all critical
directories and files used throughout the logger system.
"""

from pathlib import Path


# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Configuration
CONFIG_PATH = PROJECT_ROOT / "config.txt"

# Logging directories
LOGS_DIR = PROJECT_ROOT / "logs"
MASTER_LOG_FILE = LOGS_DIR / "master.log"

# Application state
STATE_FILE = PROJECT_ROOT / "running_modules.json"

# Module directories
MODULES_DIR = PROJECT_ROOT / "Modules"

# UI assets
UI_DIR = Path(__file__).parent / "ui"
LOGO_PATH = UI_DIR / "logo_100.png"


def ensure_directories() -> None:
    """
    Create necessary directories if they don't exist.

    Call this during application startup to ensure all required
    directories are present.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


__all__ = [
    'PROJECT_ROOT',
    'CONFIG_PATH',
    'LOGS_DIR',
    'MASTER_LOG_FILE',
    'STATE_FILE',
    'MODULES_DIR',
    'UI_DIR',
    'LOGO_PATH',
    'ensure_directories',
]
