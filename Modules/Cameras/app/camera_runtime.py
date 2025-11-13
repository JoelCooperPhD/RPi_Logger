"""Cameras runtime delegating to the MVC controller."""

from __future__ import annotations

from typing import Any

from vmc import ModuleRuntime, RuntimeContext

from ..controller import CameraController


class CamerasRuntime(ModuleRuntime):
    """Thin adapter that wires the stub supervisor into the controller layer."""

    def __init__(self, context: RuntimeContext) -> None:
        self._controller = CameraController(context)

    async def start(self) -> None:
        await self._controller.start()

    async def shutdown(self) -> None:
        await self._controller.shutdown()

    async def cleanup(self) -> None:
        await self._controller.cleanup()

    async def handle_command(self, command: dict[str, Any]) -> bool:  # type: ignore[override]
        return await self._controller.handle_command(command)

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:  # type: ignore[override]
        return await self._controller.handle_user_action(action, **kwargs)

    async def healthcheck(self) -> bool:
        return await self._controller.healthcheck()


__all__ = ["CamerasRuntime"]
