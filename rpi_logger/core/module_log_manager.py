"""
Module Log Manager - Dynamic log level control for module subprocesses.

This provides centralized logging management for modules, enabling:
1. Dynamic log level changes via commands from master
2. File logging always at DEBUG (full capture for diagnostics)
3. Console/UI logging at user-controllable levels
4. Optional log forwarding to master for unified UI display

Architecture:
    Master Process                    Module Subprocess
    ┌──────────────┐                 ┌───────────────────┐
    │ MainWindow   │ set_log_level   │ ModuleLogManager  │
    │ Log Level    │ ───────────────▶│ - file: DEBUG     │
    │ Menu         │   (command)     │ - console: varies │
    └──────────────┘                 │ - forward: varies │
                                     └───────────────────┘
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional, Any

from rpi_logger.core.logging_config import LOG_FORMAT, LOG_DATEFMT
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("ModuleLogManager")


class ForwardingHandler(logging.Handler):
    """Handler that forwards log records to master via StatusMessage.

    This enables centralized log viewing in the master's UI panel.
    The handler respects its level setting for filtering.
    """

    def __init__(self, module_id: str, level: int = logging.INFO):
        super().__init__(level)
        self.module_id = module_id
        self.setFormatter(logging.Formatter("%(name)s | %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from rpi_logger.core.commands import StatusMessage
            StatusMessage.send("log_message", {
                "level": record.levelname,
                "logger_name": record.name,
                "message": self.format(record),
                "module_id": self.module_id,
            })
        except Exception:
            pass  # Never let logging crash the module


class ModuleLogManager:
    """Manages log levels for a module subprocess.

    Key responsibilities:
    - Configure handlers at module startup
    - Handle set_log_level commands from master
    - Ensure file handler always captures DEBUG
    - Optionally forward logs to master UI

    Usage in module:
        log_manager = ModuleLogManager(module_id="DRT:ACM0")
        log_manager.setup_handlers(
            log_file=Path("logs/drt.log"),
            console_level=logging.INFO
        )

        # In command handler:
        log_manager.handle_set_log_level(command_data)
    """

    def __init__(self, module_id: str):
        """Initialize the log manager.

        Args:
            module_id: Unique module identifier (e.g., "DRT:ACM0")
        """
        self.module_id = module_id
        self._file_handler: Optional[logging.Handler] = None
        self._console_handler: Optional[logging.Handler] = None
        self._forwarding_handler: Optional[ForwardingHandler] = None
        self._console_level = logging.INFO
        self._ui_level = logging.INFO
        self._forwarding_enabled = False

    def setup_handlers(
        self,
        log_file: Optional[Path] = None,
        console_level: int = logging.INFO,
        max_bytes: int = 300 * 1024,
        backup_count: int = 3,
        enable_console: bool = True,
    ) -> None:
        """Configure logging handlers for this module.

        Args:
            log_file: Path for rotating log file (DEBUG level always)
            console_level: Initial level for console output
            max_bytes: Max bytes before log rotation
            backup_count: Number of backup files to keep
            enable_console: Whether to enable console logging
        """
        root_logger = logging.getLogger()
        formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

        # File handler - always DEBUG for full capture
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            self._file_handler.setLevel(logging.DEBUG)
            self._file_handler.setFormatter(formatter)
            root_logger.addHandler(self._file_handler)
            logger.debug("File handler configured: %s (DEBUG)", log_file)

        # Console handler - user-controllable level
        if enable_console:
            self._console_handler = logging.StreamHandler(sys.stderr)
            self._console_handler.setLevel(console_level)
            self._console_handler.setFormatter(formatter)
            root_logger.addHandler(self._console_handler)
            self._console_level = console_level
            logger.debug("Console handler configured (level: %s)",
                        logging.getLevelName(console_level))

        # Ensure root logger allows all messages through
        root_logger.setLevel(logging.DEBUG)

    def enable_forwarding(self, initial_level: int = logging.INFO) -> None:
        """Enable log forwarding to master UI.

        Args:
            initial_level: Initial level for forwarded logs
        """
        if self._forwarding_handler is not None:
            return

        self._forwarding_handler = ForwardingHandler(self.module_id, initial_level)
        logging.getLogger().addHandler(self._forwarding_handler)
        self._forwarding_enabled = True
        self._ui_level = initial_level
        logger.debug("Log forwarding enabled (level: %s)",
                    logging.getLevelName(initial_level))

    def disable_forwarding(self) -> None:
        """Disable log forwarding to master UI."""
        if self._forwarding_handler is not None:
            logging.getLogger().removeHandler(self._forwarding_handler)
            self._forwarding_handler = None
            self._forwarding_enabled = False
            logger.debug("Log forwarding disabled")

    def set_console_level(self, level: int) -> None:
        """Set the console handler's log level.

        Args:
            level: Logging level (e.g., logging.DEBUG)
        """
        if self._console_handler:
            self._console_handler.setLevel(level)
            self._console_level = level
            logger.debug("Console level set to %s", logging.getLevelName(level))

    def set_ui_level(self, level: int) -> None:
        """Set the level for logs forwarded to master UI.

        Args:
            level: Logging level (e.g., logging.INFO)
        """
        self._ui_level = level
        if self._forwarding_handler:
            self._forwarding_handler.setLevel(level)
            logger.debug("UI forwarding level set to %s", logging.getLevelName(level))

    def handle_set_log_level(self, command_data: Dict[str, Any]) -> bool:
        """Handle set_log_level command from master.

        Args:
            command_data: Command dict with 'level' and optional 'target'

        Returns:
            True if command was handled successfully
        """
        level_str = command_data.get("level", "info").upper()
        target = command_data.get("target", "all")

        # Convert string to logging level
        level = getattr(logging, level_str, logging.INFO)

        if target in ("console", "all"):
            self.set_console_level(level)

        if target in ("ui", "all"):
            self.set_ui_level(level)

        logger.info("Log level updated: level=%s, target=%s", level_str, target)
        return True

    def cleanup(self) -> None:
        """Remove all handlers and clean up resources."""
        root_logger = logging.getLogger()

        if self._file_handler:
            root_logger.removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None

        if self._console_handler:
            root_logger.removeHandler(self._console_handler)
            self._console_handler = None

        if self._forwarding_handler:
            root_logger.removeHandler(self._forwarding_handler)
            self._forwarding_handler = None

    @property
    def console_level(self) -> int:
        """Current console handler level."""
        return self._console_level

    @property
    def ui_level(self) -> int:
        """Current UI forwarding level."""
        return self._ui_level

    @property
    def forwarding_enabled(self) -> bool:
        """Whether log forwarding is enabled."""
        return self._forwarding_enabled


# Module-level singleton for easy access
_module_log_manager: Optional[ModuleLogManager] = None


def get_module_log_manager() -> Optional[ModuleLogManager]:
    """Get the module's log manager singleton."""
    return _module_log_manager


def setup_module_logging(
    module_id: str,
    log_file: Optional[Path] = None,
    console_level: int = logging.INFO,
    enable_forwarding: bool = False,
) -> ModuleLogManager:
    """Convenience function to set up module logging.

    Args:
        module_id: Unique module identifier
        log_file: Path for log file
        console_level: Initial console level
        enable_forwarding: Whether to enable log forwarding to master

    Returns:
        Configured ModuleLogManager instance
    """
    global _module_log_manager

    _module_log_manager = ModuleLogManager(module_id)
    _module_log_manager.setup_handlers(
        log_file=log_file,
        console_level=console_level,
    )

    if enable_forwarding:
        _module_log_manager.enable_forwarding(console_level)

    return _module_log_manager
