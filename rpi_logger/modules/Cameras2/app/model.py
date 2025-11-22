"""Lightweight Cameras2 model (UI/state container)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.base.config_paths import ModuleConfigContext, resolve_module_config_path
from rpi_logger.modules.base.preferences import ModulePreferences


class Cameras2Model:
    """Tracks module preferences and lifecycle signals."""

    def __init__(
        self,
        args,
        module_dir: Path,
        *,
        logger: LoggerLike = None,
        config_filename: str = "config.txt",
    ) -> None:
        self.args = args
        self.module_dir = module_dir
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self.shutdown_event = asyncio.Event()
        self.shutdown_reason: Optional[str] = None
        self.config_context: ModuleConfigContext = resolve_module_config_path(
            module_dir,
            "Cameras2",
            filename=config_filename,
        )
        self.config_path = self.config_context.writable_path
        self.preferences = ModulePreferences(self.config_path)
        self.config_data: Dict[str, Any] = self.preferences.snapshot()
        self.ready = False

    def mark_ready(self) -> None:
        self.ready = True

    def request_shutdown(self, reason: str) -> None:
        self.shutdown_reason = reason
        self.shutdown_event.set()

