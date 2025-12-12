"""Centralized path constants for the RPi Logger system."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _is_nuitka() -> bool:
    """Check if running as a Nuitka compiled binary."""
    return "__compiled__" in dir() or getattr(sys, 'frozen', False) and not hasattr(sys, '_MEIPASS')


def _is_pyinstaller() -> bool:
    """Check if running as a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def _get_base_path() -> Path:
    """Get the base path, handling normal, PyInstaller, and Nuitka environments."""
    if _is_pyinstaller():
        # Running as PyInstaller bundle
        return Path(sys._MEIPASS)
    elif _is_nuitka():
        # Running as Nuitka compiled binary - use executable directory
        return Path(sys.executable).parent
    else:
        # Running as normal Python script
        return Path(__file__).resolve().parents[2]


def _is_frozen() -> bool:
    """Check if running as a frozen/compiled application (PyInstaller or Nuitka)."""
    return _is_pyinstaller() or _is_nuitka()


# Base path (handles frozen vs normal)
_BASE_PATH = _get_base_path()

# Project/package roots
if _is_frozen():
    PROJECT_ROOT = _BASE_PATH
    PACKAGE_ROOT = _BASE_PATH / "rpi_logger"
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    PACKAGE_ROOT = PROJECT_ROOT / "rpi_logger"

# Configuration
CONFIG_PATH = PROJECT_ROOT / "config.txt"

# Logging directories
LOGS_DIR = PROJECT_ROOT / "logs"
MASTER_LOG_FILE = LOGS_DIR / "master.log"

# Application state
STATE_FILE = PROJECT_ROOT / "running_modules.json"

# Module directories
MODULES_DIR = PACKAGE_ROOT / "modules"

# User-specific state (allows running from read-only project directories)
_USER_STATE_ENV = os.environ.get("RPI_LOGGER_STATE_DIR")
USER_STATE_DIR = Path(_USER_STATE_ENV).expanduser() if _USER_STATE_ENV else (Path.home() / ".rpi_logger")
USER_CONFIG_OVERRIDES_DIR = USER_STATE_DIR / "config_overrides"
USER_MODULE_CONFIG_DIR = USER_STATE_DIR / "module_configs"
USER_MODULE_LOGS_DIR = USER_STATE_DIR / "module_logs"

# UI assets
UI_DIR = Path(__file__).parent / "ui"
LOGO_PATH = UI_DIR / "logo_100.png"
ICON_PATH = UI_DIR / "icon.png"  # Network graph icon for system tray


def ensure_directories() -> None:
    """Create necessary directories if they don't exist."""

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    USER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    USER_MODULE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USER_MODULE_LOGS_DIR.mkdir(parents=True, exist_ok=True)


__all__ = [
    'PROJECT_ROOT',
    'PACKAGE_ROOT',
    'CONFIG_PATH',
    'LOGS_DIR',
    'MASTER_LOG_FILE',
    'STATE_FILE',
    'MODULES_DIR',
    'USER_STATE_DIR',
    'USER_CONFIG_OVERRIDES_DIR',
    'USER_MODULE_CONFIG_DIR',
    'USER_MODULE_LOGS_DIR',
    'UI_DIR',
    'LOGO_PATH',
    'ICON_PATH',
    'ensure_directories',
    '_is_frozen',
    '_is_nuitka',
    '_is_pyinstaller',
]
