"""Cameras controller stub."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import RuntimeStatus
from rpi_logger.modules.Cameras.runtime.registry import Registry


class CamerasController:
    """Coordinates registry/router lifecycle and bridges commands."""

    def __init__(self, registry: Registry, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._registry = registry

    async def start(self) -> None:
        self._logger.info("Cameras controller started")

    async def shutdown(self) -> None:
        self._logger.info("Cameras controller shutting down")

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action in {"start_recording", "stop_recording", "get_status"}:
            self._logger.debug("Received command %s", action)
            return True
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        if action in {"start_recording", "stop_recording", "quit", "get_status"}:
            self._logger.debug("User action %s", action)
            return True
        return False

    async def healthcheck(self) -> Dict[str, Any]:
        snapshot = self._registry.snapshot()
        return {
            "cameras": len(snapshot),
            "statuses": {key: state.status.value for key, state in snapshot.items()},
        }

