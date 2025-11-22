"""USB Cameras runtime delegating to the controller layer."""

from __future__ import annotations

from typing import Any

from vmc import ModuleRuntime, RuntimeContext

from ..controller import USBCameraController
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


class USBCamerasRuntime(ModuleRuntime):
    """Thin adapter that wires the stub supervisor into the USB camera controller."""

    def __init__(self, context: RuntimeContext) -> None:
        self._controller = USBCameraController(context)
        logger.debug("USBCamerasRuntime initialized")

    async def start(self) -> None:
        logger.debug("USBCamerasRuntime start requested")
        await self._controller.start()

    async def shutdown(self) -> None:
        logger.debug("USBCamerasRuntime shutdown requested")
        await self._controller.shutdown()

    async def cleanup(self) -> None:
        logger.debug("USBCamerasRuntime cleanup requested")
        await self._controller.cleanup()

    async def handle_command(self, command: dict[str, Any]) -> bool:  # type: ignore[override]
        logger.debug("Routing supervisor command | command=%s", command.get("command"))
        return await self._controller.handle_command(command)

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:  # type: ignore[override]
        logger.debug("Routing user action | action=%s", action)
        return await self._controller.handle_user_action(action, **kwargs)

    async def healthcheck(self) -> bool:
        healthy = await self._controller.healthcheck()
        logger.debug("USBCamerasRuntime healthcheck | healthy=%s", healthy)
        return healthy


__all__ = ["USBCamerasRuntime"]
