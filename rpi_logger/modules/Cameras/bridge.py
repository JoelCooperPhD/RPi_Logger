"""Cameras runtime delegating to the MVC controller."""

from __future__ import annotations

from typing import Any

from vmc import ModuleRuntime, RuntimeContext

from .controller import CameraController
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


class CamerasRuntime(ModuleRuntime):
    """Thin adapter that wires the stub supervisor into the controller layer."""

    def __init__(self, context: RuntimeContext) -> None:
        self._controller = CameraController(context)
        logger.debug("CamerasRuntime initialized")

    async def start(self) -> None:
        logger.debug("CamerasRuntime start requested")
        await self._controller.start()

    async def shutdown(self) -> None:
        logger.debug("CamerasRuntime shutdown requested")
        await self._controller.shutdown()

    async def cleanup(self) -> None:
        logger.debug("CamerasRuntime cleanup requested")
        await self._controller.cleanup()

    async def handle_command(self, command: dict[str, Any]) -> bool:  # type: ignore[override]
        logger.debug("Routing supervisor command | command=%s", command.get("command"))
        return await self._controller.handle_command(command)

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:  # type: ignore[override]
        logger.debug("Routing user action | action=%s", action)
        return await self._controller.handle_user_action(action, **kwargs)

    async def healthcheck(self) -> bool:
        healthy = await self._controller.healthcheck()
        logger.debug("CamerasRuntime healthcheck | healthy=%s", healthy)
        return healthy


__all__ = ["CamerasRuntime"]
