"""Centralized path constants for the RPi Logger system."""

from __future__ import annotations

import os
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

# User-specific state (allows running from read-only project directories)
_USER_STATE_ENV = os.environ.get("RPI_LOGGER_STATE_DIR")
USER_STATE_DIR = Path(_USER_STATE_ENV).expanduser() if _USER_STATE_ENV else (Path.home() / ".rpi_logger")
USER_CONFIG_OVERRIDES_DIR = USER_STATE_DIR / "config_overrides"
USER_MODULE_LOGS_DIR = USER_STATE_DIR / "module_logs"
SESSION_STAGING_DIR = USER_STATE_DIR / "staging"

# UI assets
UI_DIR = Path(__file__).parent / "ui"
LOGO_PATH = UI_DIR / "logo_100.png"


def ensure_directories() -> None:
    """Create necessary directories if they don't exist."""

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    USER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    USER_MODULE_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_STAGING_DIR.mkdir(parents=True, exist_ok=True)


__all__ = [
    'PROJECT_ROOT',
    'CONFIG_PATH',
    'LOGS_DIR',
    'MASTER_LOG_FILE',
    'STATE_FILE',
    'MODULES_DIR',
    'USER_STATE_DIR',
    'USER_CONFIG_OVERRIDES_DIR',
    'USER_MODULE_LOGS_DIR',
    'SESSION_STAGING_DIR',
    'UI_DIR',
    'LOGO_PATH',
    'ensure_directories',
]
